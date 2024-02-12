import platform
import sys
from unittest import TestCase
from unittest.mock import patch

from dispatcher.dispatcher import main, WindowsDispatcherService, make_dispatcher


class TestDispatcher(TestCase):

    @patch('servicemanager.Initialize')
    @patch('servicemanager.PrepareToHostSingle')
    @patch('servicemanager.StartServiceCtrlDispatcher')
    def test_windows_dispatcher_service(self, mock_start_service_ctrl_dispatcher, mock_prepare_to_host_single,
                                        mock_initialize):
        sys.argv = []
        with patch('platform.system', return_value='Windows'):
            main()
        mock_initialize.assert_called_once()
        mock_prepare_to_host_single.assert_called_once_with(WindowsDispatcherService)
        mock_start_service_ctrl_dispatcher.assert_called_once()

    @patch('win32serviceutil.HandleCommandLine')
    def test_windows_dispatcher_service_with_command_line(self, mock_handle_command_line):
        sys.argv = ['some_argument']
        with patch('platform.system', return_value='Windows'):
            main()
        mock_handle_command_line.assert_called_once_with(WindowsDispatcherService)

    @patch('make_dispatcher')
    def test_non_windows_dispatcher_service(self, mock_make_dispatcher):
        sys.argv = ['some_argument']
        with patch('platform.system', return_value='Linux'):
            main()
        mock_make_dispatcher.assert_called_once_with(sys.argv)
        mock_make_dispatcher.return_value.start.assert_called_once()
