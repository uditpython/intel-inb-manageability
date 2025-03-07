"""
    Copyright (C) 2023 Intel Corporation
    SPDX-License-Identifier: Apache-2.0
"""

import glob
import logging
import os
from dispatcher.dispatcher_exception import DispatcherException
from dispatcher.source.constants import (
    UBUNTU_APT_SOURCES_LIST,
    UBUNTU_APT_SOURCES_LIST_D,
    ApplicationAddSourceParameters,
    ApplicationRemoveSourceParameters,
    ApplicationSourceList,
    ApplicationUpdateSourceParameters,
    SourceParameters,
)
from dispatcher.source.source_manager import ApplicationSourceManager, OsSourceManager
from inbm_common_lib.shell_runner import PseudoShellRunner

logger = logging.getLogger(__name__)


class UbuntuOsSourceManager(OsSourceManager):
    def __init__(self) -> None:
        pass

    def add(self, parameters: SourceParameters) -> None:
        """Adds a source in the Ubuntu OS source file /etc/apt/sources.list"""
        # TODO: Add functionality to add a source file in Ubuntu to /etc/apt/sources.list file
        logger.debug(f"sources: {parameters.sources}")

    def list(self) -> list[str]:
        """List deb and deb-src lines in /etc/apt/sources.list"""
        try:
            with open(UBUNTU_APT_SOURCES_LIST, "r") as file:
                lines = [
                    line.strip()
                    for line in file.readlines()
                    if line.strip() and not line.startswith("#")
                ]
            return [
                line for line in lines if line.startswith("deb ") or line.startswith("deb-src ")
            ]
        except OSError as e:
            logger.error(f"Error opening source file: {e}")
            raise DispatcherException(f"Error opening source file: {e}") from e

    def remove(self, parameters: SourceParameters) -> None:
        """Removes a source in the Ubuntu OS source file /etc/apt/sources.list"""

        sources_list_path = UBUNTU_APT_SOURCES_LIST
        try:
            with open(sources_list_path, "r") as file:
                lines = file.readlines()

            sources_to_remove = set(source.strip() for source in parameters.sources)

            # Filter out any lines that exactly match the given sources
            with open(sources_list_path, "w") as file:
                for line in lines:
                    if line.strip() not in sources_to_remove:
                        file.write(line)
                    else:
                        logger.debug(f"Removed source: {line}")

        except OSError as e:
            # Wrap any OSError exceptions in a DispatcherException and re-raise.
            logger.error(f"Error occurred while trying to remove sources: {e}")
            raise DispatcherException(f"Error occurred while trying to remove sources: {e}") from e

    def update(self, parameters: SourceParameters) -> None:
        """Updates a source in the Ubuntu OS source file /etc/apt/sources.list"""
        # TODO: Add functionality to update a source in Ubuntu file under /etc/apt/sources.list file
        logger.debug(f"sources: {parameters.sources}")


class UbuntuApplicationSourceManager(ApplicationSourceManager):
    def __init__(self) -> None:
        pass

    def add(self, parameters: ApplicationAddSourceParameters) -> None:
        """Adds new application source along with its key"""
        pass

    def list(self) -> list[ApplicationSourceList]:
        """List Ubuntu Application source lists under /etc/apt/sources.list.d"""
        sources = []
        try:
            for filepath in glob.glob(UBUNTU_APT_SOURCES_LIST_D + "/*"):
                with open(filepath, "r") as file:
                    lines = [
                        line.strip()
                        for line in file.readlines()
                        if line.strip() and not line.startswith("#")
                    ]
                    new_source = ApplicationSourceList(
                        name=os.path.basename(filepath),
                        sources=[
                            line
                            for line in lines
                            if line.startswith("deb ") or line.startswith("deb-src ")
                        ],
                    )
                    sources.append(new_source)
            return sources
        except OSError as e:
            logger.error(f"Error listing application sources: {e}")
            raise DispatcherException(f"Error listing application sources: {e}") from e

    def remove(self, parameters: ApplicationRemoveSourceParameters) -> None:
        """Removes a source file from the Ubuntu source file list under /etc/apt/sources.list.d"""
        # Remove the GPG key
        try:
            stdout, stderr, exit_code = PseudoShellRunner().run(
                f"gpg --list-keys {parameters.gpg_key_id}"
            )

            # If the key exists, try to remove it
            if exit_code == 0:
                stdout, stderr, exit_code = PseudoShellRunner().run(
                    f"gpg --delete-key {parameters.gpg_key_id}"
                )
                if exit_code != 0:
                    raise DispatcherException("Error deleting GPG key: " + (stderr or stdout))

        except OSError as e:
            logger.error(f"Error checking or deleting GPG key: {e}")
            raise DispatcherException(f"Error checking or deleting GPG key: {e}") from e

        # Remove the file under /etc/apt/sources.list.d
        try:
            os.remove(UBUNTU_APT_SOURCES_LIST_D + "/" + parameters.file_name)
        except OSError as e:
            raise DispatcherException(f"Error removing file: {e}") from e

    def update(self, parameters: ApplicationUpdateSourceParameters) -> None:
        """Updates a source file in Ubuntu OS source file list under /etc/apt/sources.list.d"""
        # TODO: Add functionality to update a Ubuntu source file under /etc/apt/sources.list.d
        logger.debug(f"file_name: {parameters.file_name}, source: {parameters.sources[0]}")
