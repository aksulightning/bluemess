"""Non-destructive installer tests; never open, attach, or write block devices.

Run under BusyBox ash with BME_TEST_SHELL='busybox ash' python3 -m unittest
discover -s tests. Default dash supplies an additional portable-shell check.
The real partition/extraction path is exercised only by vm/verify.py in QEMU.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "installer/lib/install.sh"
SHELL = shlex.split(os.environ.get("BME_TEST_SHELL", "dash"))


class InstallerTests(unittest.TestCase):
    def shell(self, code, *args):
        return subprocess.run(
            SHELL + ["-c", '. "$1"; shift; ' + code, "bme-test", str(LIB), *args],
            text=True, capture_output=True, timeout=10,
        )

    def test_shell_syntax(self):
        for path in (LIB, ROOT / "installer/bme-install"):
            result = subprocess.run(SHELL + ["-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_hostnames(self):
        for value in ("bme", "desktop-1", "a", "A01"):
            with self.subTest(value=value):
                self.assertEqual(self.shell('bme_valid_hostname "$1"', value).returncode, 0)
        for value in ("", "-bme", "bme-", "a.b", "a b", "a" * 64, "$(touch /tmp/should-not-exist)"):
            with self.subTest(value=value):
                self.assertNotEqual(self.shell('bme_valid_hostname "$1"', value).returncode, 0)

    def test_usernames_and_reserved_accounts(self):
        for value in ("alice", "bme-user", "user_1"):
            self.assertEqual(self.shell('bme_valid_username "$1"', value).returncode, 0)
        for value in ("root", "daemon", "_apt", "nobody", "Alice", "--root", "u:0", "a" * 33):
            self.assertNotEqual(self.shell('bme_valid_username "$1"', value).returncode, 0)

    def test_target_requires_explicit_whole_block_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            regular = Path(tmp) / "not-a-disk"
            regular.touch()
            for value in ("", "/", str(regular), "/dev/this-device-does-not-exist"):
                result = self.shell('BME_DISK=$1; bme_validate_disk', value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_bad_payload_does_not_invoke_destructive_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bme").mkdir()
            (folder / "bme/rootfs.tar.zst").write_bytes(b"tampered")
            (folder / "bme/SHA256SUMS").write_text("0" * 64 + "  rootfs.tar.zst\n")
            result = self.shell('BME_MEDIA=$1; BME_LOG=$1/log; bme_verify_payload', tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch; no disk changes made", result.stderr)

    def test_duplicate_or_malformed_payload_checksum_rejected(self):
        for manifest in (
            "../rootfs.tar.zst\n",
            "x" * 64 + "  rootfs.tar.zst\n",
            ("0" * 64 + "  rootfs.tar.zst\n") * 2,
        ):
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                (folder / "bme").mkdir()
                (folder / "bme/rootfs.tar.zst").write_bytes(b"data")
                (folder / "bme/SHA256SUMS").write_text(manifest)
                result = self.shell('BME_MEDIA=$1; BME_LOG=$1/log; bme_verify_payload', tmp)
                self.assertNotEqual(result.returncode, 0)

    def test_password_permissions_and_no_secret_logging(self):
        with tempfile.TemporaryDirectory() as tmp:
            password = Path(tmp) / "password"
            password.write_text("test-secret-123\n")
            password.chmod(0o644)
            # Root ownership is emulated only at stat's UID boundary; modes and
            # contents remain real files so this also runs as an ordinary user.
            code = '''
                stat() { if [ "$2" = %u ]; then printf '0\\n'; else command stat "$@"; fi; }
                BME_UNATTENDED=1; BME_PASSWORD_FILE=$1; bme_read_password
            '''
            result = self.shell(code, str(password))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("test-secret-123", result.stdout + result.stderr)
            password.chmod(0o600)
            result = self.shell(code, str(password))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("test-secret-123", result.stdout + result.stderr)
            password.write_text("test-secret-123\nextra-line\n")
            self.assertNotEqual(self.shell(code, str(password)).returncode, 0)

    def test_dry_run_never_calls_payload_or_install_engine(self):
        # Inject harmless validation boundaries; neither payload reads, password
        # reads nor the destructive engine may be invoked during a dry run.
        result = self.shell('''
            id() { printf '0\\n'; }
            bme_validate_disk() { :; }
            bme_validate_settings() { :; }
            lsblk() { :; }
            bme_verify_payload() { echo UNEXPECTED_PAYLOAD; exit 90; }
            bme_read_password() { echo UNEXPECTED_PASSWORD; exit 91; }
            bme_install_engine() { echo UNEXPECTED_ERASE; exit 92; }
            bme_main --dry-run --unattended --disk /dev/disposable-test-only
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run complete: no disk changes made.", result.stdout)
        self.assertNotIn("UNEXPECTED", result.stdout + result.stderr)

    def test_unattended_acknowledgement_is_disk_specific(self):
        result = self.shell('''
            BME_DISK=/dev/disposable-test-only
            BME_ACK=ERASE:/dev/different-device
            bme_require_acknowledgement
            echo UNEXPECTED_ERASE
        ''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("UNEXPECTED_ERASE", result.stdout + result.stderr)
        self.assertIn("acknowledgement", result.stderr)
        valid = self.shell('BME_DISK=/dev/test; BME_ACK=ERASE:/dev/test; bme_require_acknowledgement')
        self.assertEqual(valid.returncode, 0, valid.stderr)

    def test_mounted_partition_rejects_its_backing_disk(self):
        result = self.shell('''
            lsblk() { printf '/dev/disposable\\n/dev/disposable1\\n'; }
            findmnt() { [ "$3" != /dev/disposable1 ] || printf '/mounted\\n'; }
            BME_MEDIA=/run/bme-media
            bme_disk_is_used /dev/disposable
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_installer_media_ancestor_is_protected(self):
        result = self.shell('''
            lsblk() {
                if [ "$1" = -snrpo ]; then printf '/dev/media1\\n/dev/disposable\\n';
                else printf '/dev/disposable\\n'; fi
            }
            findmnt() { [ "$2" != -T ] || printf '/dev/media1\\n'; }
            BME_MEDIA=/run/bme-media
            bme_disk_is_used /dev/disposable
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
