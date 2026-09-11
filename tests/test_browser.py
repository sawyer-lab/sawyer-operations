from unittest.mock import Mock

import pytest

from sawyer_operations import browser


def test_explicit_chromium_owns_profile_and_closes_only_its_process_group(monkeypatch):
    monkeypatch.setattr('sys.argv', ['viewer', '--browser', 'chromium'])
    monkeypatch.setattr(browser.shutil, 'which', lambda name: '/usr/bin/chromium')
    child = Mock(pid=98765)
    child.wait.side_effect = [KeyboardInterrupt(), 0]
    child.poll.return_value = None
    launch = Mock(return_value=child)
    kill = Mock()
    monkeypatch.setattr(browser.subprocess, 'Popen', launch)
    monkeypatch.setattr(browser.os, 'killpg', kill)
    monkeypatch.setattr(browser.signal, 'signal', Mock())
    browser.main()
    args = launch.call_args.args[0]
    assert args[0] == '/usr/bin/chromium'
    assert any(arg.startswith('--user-data-dir=') for arg in args)
    assert launch.call_args.kwargs['start_new_session'] is True
    kill.assert_called_once_with(98765, browser.signal.SIGTERM)


def test_missing_explicit_browser_does_not_silently_open_another(monkeypatch):
    monkeypatch.setattr('sys.argv', ['viewer', '--browser', 'chromium'])
    monkeypatch.setattr(browser.shutil, 'which', lambda name: None)
    with pytest.raises(SystemExit, match='Browser executable not found: chromium'):
        browser.main()
