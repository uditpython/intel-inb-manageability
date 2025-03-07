"""
    SOTA update tool which is called from the dispatcher during installation

    Copyright (C) 2017-2023 Intel Corporation
    SPDX-License-Identifier: Apache-2.0
"""

import logging
import os
import re
import time
from typing import Any, List, Optional, Union, Mapping

from inbm_common_lib.exceptions import UrlSecurityException
from inbm_common_lib.utility import canonicalize_uri
from inbm_common_lib.request_message_constants import SOTA_FAILURE
from inbm_common_lib.constants import REMOTE_SOURCE, LOCAL_SOURCE
from inbm_lib.validate_package_list import parse_and_validate_package_list
from inbm_lib.detect_os import detect_os
from inbm_lib.constants import OTA_PENDING, OTA_FAIL, OTA_SUCCESS

from dispatcher.dispatcher_exception import DispatcherException
from .command_handler import run_commands, print_execution_summary, get_command_status
from .constants import SUCCESS, SOTA_STATE, SOTA_CACHE, PROCEED_WITHOUT_ROLLBACK_DEFAULT
from .downloader import Downloader
from .log_helper import get_log_destination
from .os_factory import ISotaOs, SotaOsFactory
from .os_updater import OsUpdater
from .rebooter import Rebooter
from .setup_helper import SetupHelper
from .snapshot import Snapshot
from .sota_error import SotaError
from ..packagemanager.local_repo import DirectoryRepo, IRepo
from ..install_check_service import InstallCheckService
from ..update_logger import UpdateLogger
from ..dispatcher_broker import DispatcherBroker

logger = logging.getLogger(__name__)


class SOTAUtil:  # FIXME intermediate step in refactor
    def check_diagnostic_disk(self,
                              estimated_size: Union[float, int],
                              dispatcher_broker: DispatcherBroker,
                              install_check_service: InstallCheckService) -> None:
        """Checks if there is sufficient size for an update with diagnostic agent

        @param estimated_size: estimated install size
        @param dispatcher_broker: DispatcherBroker object used to communicate with other INBM services
        @param install_check_service: provides an install check
        """
        logger.debug("")
        logger.info(f'Estimate reports we need additional {estimated_size} Bytes for update')
        try:
            install_check_service.install_check(size=estimated_size, check_type='check_storage')
        except DispatcherException:
            dispatcher_broker.telemetry(
                "System Update aborted: insufficient disk space")
            raise SotaError('Insufficient disk space for update')


class SOTA:
    """AKA SOTA tool or System Over the Air Tool

    An Instance of this class will be called from the dispatcher if the
    requested type of update if SOTA

    We create instances of this class in two modes: normal and then rollback mode
    after reboot

    It executes installs,upgrades,removes packages.
    Also, It can apply security and perform LTS upgrades.

    @param dispatcher: callback to dispatcher
    """

    def __enter__(self):
        return self

    def __init__(self,
                 parsed_manifest: Mapping[str, Optional[Any]],
                 repo_type: str,
                 dispatcher_broker: DispatcherBroker,
                 update_logger: UpdateLogger,
                 sota_repos: Optional[str],
                 install_check_service: InstallCheckService,
                 snapshot: Optional[Any] = None,
                 action: Optional[Any] = None) -> None:
        """SOTA thread instance

        @param parsed_manifest: Parsed parameters from manifest
        @param repo_type: OTA source location -> local or remote
        @param dispatcher_broker: DispatcherBroker object used to communicate with other INBM services
        @param sota_repos: new Ubuntu/Debian mirror (or None)
        @param update_logger: UpdateLogger instance--expected to notify it with update status
        @param kwargs:
        """

        self._parsed_manifest = parsed_manifest
        self._username = parsed_manifest['username']
        self._password = parsed_manifest['password']
        self._ota_element = parsed_manifest.get('resource')
        self._uri: Optional[str] = parsed_manifest['uri']
        self._repo_type = repo_type
        self.sota_state = SOTA_STATE
        self.sota_cmd: Optional[str] = None
        self.snap_num: Optional[str] = None
        self.log_to_file: Optional[str] = None
        self._sota_repos = sota_repos
        self.installer: Union[None, OsUpdater] = None
        self.factory: Optional[ISotaOs] = None
        self.proceed_without_rollback = PROCEED_WITHOUT_ROLLBACK_DEFAULT
        self.sota_mode = parsed_manifest['sota_mode']
        self._update_logger = update_logger
        self._dispatcher_broker = dispatcher_broker

        try:
            manifest_package_list = parsed_manifest['package_list']
        except KeyError:
            manifest_package_list = ''
        try:
            # If manifest_package_list is None, treat it as an empty string, otherwise, convert to string
            self._package_list: str = "" if manifest_package_list is None else str(
                manifest_package_list)
        except (ValueError, TypeError) as e:
            # If an exception occurs during string conversion, raise that exception
            raise SotaError('package_list is not a string in manifest') from e

        self._device_reboot = parsed_manifest['deviceReboot']
        self._install_check_service = install_check_service

        if self._repo_type == LOCAL_SOURCE:
            if self._ota_element is None:
                raise SotaError("ota_element is missing for SOTA")
            self._local_file_path = self._ota_element['path']

        if snapshot is not None:
            self.snap_num = snapshot
        if action is not None:
            self.sota_state = action

        logger.debug(f"SOTA Tool launched in {self.sota_state} mode")

    def _clean_local_repo_file(self) -> None:
        local_cache_repo = DirectoryRepo(self._local_file_path.rsplit('/', 1)[0])
        local_cache_repo.delete_all()
        logger.debug("Deleting files in {}.".format(
            self._local_file_path.rsplit('/', 1)[0]))

    def calculate_and_execute_sota_upgrade(self, repo: IRepo) -> List:
        """Calculate commands for SOTA upgrade and execute them.

        @param repo: directory (Repo) where we may have downloaded OS updates (depending on OS)
        @return: command list
        """
        logger.debug("")

        cmd_list: List = []
        if (self.sota_cmd == 'update' and self.sota_mode is None) or (self.sota_mode == 'full'):
            # the following line will be optimized out in byte code and only used in unit testing
            assert self.factory  # noqa: S101
            self.installer = self.factory.create_os_updater()
            estimated_size = self.installer.get_estimated_size()
            SOTAUtil().check_diagnostic_disk(estimated_size, self._dispatcher_broker,
                                             self._install_check_service)
            if self._repo_type == REMOTE_SOURCE:
                logger.debug(f"Remote repo URI: {self._uri}")
                if self._uri is None:
                    cmd_list = self.installer.update_remote_source(None, repo)
                else:
                    cmd_list = self.installer.update_remote_source(
                        canonicalize_uri(self._uri), repo)
            else:
                cmd_list = self.installer.update_local_source(self._local_file_path)
        elif self.sota_cmd == 'upgrade':
            raise SotaError('SOTA upgrade is no longer supported')
        elif self.sota_mode == 'no-download':
            assert self.factory  # noqa: S101
            self.installer = self.factory.create_os_updater()
            cmd_list = self.installer.no_download()
        elif self.sota_mode == 'download-only':
            assert self.factory  # noqa: S101
            self.installer = self.factory.create_os_updater()
            cmd_list = self.installer.download_only()

        log_destination = get_log_destination(self.log_to_file, self.sota_cmd)
        run_commands(log_destination=log_destination,
                     cmd_list=cmd_list,
                     dispatcher_broker=self._dispatcher_broker)
        return cmd_list

    def execute(self, proceed_without_rollback: bool, skip_sleeps: bool = False) -> None:  # pragma: no cover
        """Entry point into the SOTA Module. Prints summary at the end before rebooting

        If everything was fine after reboot by SOTA, 'diagnostic_system_healthy' is set which means
        we only delete snapshot
        If things are not fine after reboot by SOTA, 'diagnostic_system_unhealthy' is set which
        means we revert to snapshot and then delete the snapshot

        skip_sleeps shall be set to True to skip sleeps in this method (for unit testing)
        """
        logger.debug("")

        self.proceed_without_rollback = proceed_without_rollback
        self.log_to_file = self._parsed_manifest['log_to_file']
        self.sota_cmd = self._parsed_manifest['sota_cmd']
        if self.sota_cmd is None:
            raise SotaError('sota_cmd is None')
        release_date = self._parsed_manifest['release_date']
        if not os.path.exists(SOTA_CACHE):
            try:
                os.mkdir(SOTA_CACHE)
            except OSError as e:
                logger.debug(f"SOTA cache directory {SOTA_CACHE} cannot be created: {e}")
                raise SotaError("SOTA cache directory cannot be created") from e
        elif not os.path.isdir(SOTA_CACHE):
            logger.debug(
                f"SOTA cache directory {SOTA_CACHE} already exists and is not a directory")
            raise SotaError(
                "SOTA cache directory already exists and is not a directory")
        sota_cache_repo = DirectoryRepo(SOTA_CACHE)

        time_to_wait_before_reboot = 2 if not skip_sleeps else 0

        validated_package_list = parse_and_validate_package_list(self._package_list)
        if validated_package_list is None:
            raise SotaError(F'parsing and validating package list: {self._package_list} failed')

        os_factory = SotaOsFactory(self._dispatcher_broker,
                                   self._sota_repos, validated_package_list)
        try:
            os_type = detect_os()
        except ValueError as e:
            if self._repo_type == LOCAL_SOURCE:
                self._clean_local_repo_file()
            raise SotaError("Invalid OS or unable to detect OS for SOTA: {}".format(str(e)))

        self.factory = os_factory.get_os(os_type)
        setup_helper = self.factory.create_setup_helper()
        if self.sota_cmd == 'rollback':
            self.snap_num = setup_helper.get_snapper_snapshot_number()
        snapshot = self.factory.create_snapshotter(
            self.sota_cmd, self.snap_num, self.proceed_without_rollback)
        rebooter = self.factory.create_rebooter()

        if self.sota_state == 'diagnostic_system_unhealthy':
            self._update_logger.update_log(OTA_FAIL)
            snapshot.revert(rebooter, time_to_wait_before_reboot)
        elif self.sota_state == 'diagnostic_system_healthy':
            try:
                snapshot.update_system()
                msg = "SUCCESSFUL INSTALL: Overall SOTA update successful.  System has been properly updated."
                logger.debug(msg)
                self._dispatcher_broker.send_result(msg)
                snapshot.commit()
            except SotaError as e:
                msg = "FAILED INSTALL: System has not been properly updated; reverting."
                logger.debug(str(e))
                self._dispatcher_broker.send_result(msg)
                self._update_logger.update_log(OTA_FAIL)
                snapshot.revert(rebooter, time_to_wait_before_reboot)
        else:
            self.execute_from_manifest(setup_helper=setup_helper,
                                       sota_cache_repo=sota_cache_repo,
                                       snapshotter=snapshot,
                                       rebooter=rebooter,
                                       time_to_wait_before_reboot=time_to_wait_before_reboot,
                                       release_date=release_date)

    def _download_sota_files(self, sota_cache_repo: IRepo, release_date: Optional[str]) -> None:
        """Download SOTA files from either a remote source or use a local source, and clean the cache directory.

        This method is responsible for downloading the necessary SOTA files from the specified remote source or
        using the local source. It also cleans the cache directory before the download process.

        @param sota_cache_repo: Repo object to store the downloaded files, and to delete all files from cache directory.
        @param release_date: The release date of the SOTA manifest, used for filtering downloads from the remote source.
        """

        sota_cache_repo.delete_all()  # clean cache directory
        # the following line will be optimized out in byte code and only used in unit testing
        assert self.factory  # noqa: S101
        if self._repo_type.lower() == REMOTE_SOURCE:
            downloader: Downloader = self.factory.create_downloader()
            logger.debug(f"SOTA Download URI: {self._uri}")
            if self._uri is None:
                downloader.download(
                    self._dispatcher_broker, None, sota_cache_repo,
                    self._username, self._password, release_date)
            else:
                downloader.download(
                    self._dispatcher_broker, canonicalize_uri(
                        self._uri), sota_cache_repo,
                    self._username, self._password, release_date)

    def execute_from_manifest(self,
                              setup_helper: SetupHelper,
                              sota_cache_repo: IRepo,
                              snapshotter: Snapshot,
                              rebooter: Rebooter,
                              time_to_wait_before_reboot: int,
                              release_date: Optional[str]) -> None:
        """This method executes SOTA from a manifest on initial boot.

        This is in contrast to resuming execution on a subsequent boot.

        @param setup_helper: Provides method to do system check before SOTA.
        @param sota_cache_repo: Repo object. Download any required files here.
        @param snapshotter: Provides method to snapshot system before performing update.
        @param rebooter: Provides method to reboot the system.
        @param time_to_wait_before_reboot: Policy: wait this many seconds before rebooting.
        @param release_date: manifest release date
        """

        cmd_list: List = []
        success = False
        download_success = False

        try:
            if setup_helper.pre_processing():
                self._download_sota_files(sota_cache_repo, release_date)
                download_success = True
                snapshotter.take_snapshot()
                cmd_list = self.calculate_and_execute_sota_upgrade(sota_cache_repo)
                sota_cache_repo.delete_all()  # clean cache directory
                if get_command_status(cmd_list) == SUCCESS:
                    self._dispatcher_broker.send_result(
                        '{"status": 200, "message": SOTA command status: SUCCESSFUL"}')
                    success = True
                else:
                    self._dispatcher_broker.telemetry(
                        '{"status": 400, "message": "SOTA command status: FAILURE"}')
                    if self.sota_mode != 'download-only':
                        snapshotter.recover(rebooter, time_to_wait_before_reboot)
        except (DispatcherException, SotaError, UrlSecurityException) as e:
            msg = "Caught exception during SOTA: " + str(e)
            logger.debug(msg)
            self._dispatcher_broker.telemetry(str(e))
            self._dispatcher_broker.send_result(
                '{"status": 400, "message": "SOTA command status: FAILURE"}')
            if download_success and self.sota_mode != 'download-only':
                snapshotter.recover(rebooter, time_to_wait_before_reboot)
            self._update_logger.status = OTA_FAIL
            self._update_logger.error = ""
            self._update_logger.save_log()
            raise SotaError(str(msg))
        finally:
            if self._repo_type == LOCAL_SOURCE:
                self._clean_local_repo_file()
            print_execution_summary(cmd_list, self._dispatcher_broker)
            if success:
                # Save the log before reboot
                if self.sota_mode == 'download-only':
                    self._update_logger.status = OTA_SUCCESS
                    self._update_logger.error = ""
                else:
                    self._update_logger.status = OTA_PENDING
                    self._update_logger.error = ""
                self._update_logger.save_log()
                if self.sota_mode == 'download-only' or self._device_reboot in ["No", "N", "n", "no", "NO"]:  # pragma: no cover
                    self._dispatcher_broker.telemetry("No reboot (SOTA pass)")
                else:
                    self._dispatcher_broker.telemetry("Going to reboot (SOTA pass)")
                    time.sleep(time_to_wait_before_reboot)
                    rebooter.reboot()

            else:
                # Save the log before reboot
                self._update_logger.status = OTA_FAIL
                self._update_logger.error = ""
                self._update_logger.save_log()
                self._dispatcher_broker.telemetry(SOTA_FAILURE)
                self._dispatcher_broker.send_result(SOTA_FAILURE)
                raise SotaError(SOTA_FAILURE)

    def check(self) -> None:
        """Perform manifest checking before SOTA"""
        logger.debug("")
        validated_package_list = parse_and_validate_package_list(self._package_list)
        if validated_package_list is None:
            raise SotaError(F'parsing and validating package list: {self._package_list} failed')
        os_factory = SotaOsFactory(self._dispatcher_broker,
                                   self._sota_repos, validated_package_list)
        try:
            os_type = detect_os()
        except ValueError as e:
            if self._repo_type == LOCAL_SOURCE:
                self._clean_local_repo_file()
            raise SotaError("Invalid OS or unable to detect OS for SOTA: {}".format(str(e)))
        self.factory = os_factory.get_os(os_type)
        downloader: Downloader = self.factory.create_downloader()
        if not downloader.check_release_date(self._parsed_manifest['release_date']):
            raise SotaError("SOTA release date older than the system's release date")
