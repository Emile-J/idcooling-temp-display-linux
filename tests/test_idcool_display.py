from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock

import idcool_display as driver


class FrameTests(unittest.TestCase):
    def test_known_temperature_frame(self) -> None:
        report = driver.frame(driver.CMD_CPU_TEMPERATURE, 77)
        self.assertEqual(len(report), 64)
        self.assertEqual(report[:7], bytes.fromhex("55 bb 02 01 00 4d 60"))
        self.assertEqual(report[7:], bytes(57))

    def test_rejects_unknown_command(self) -> None:
        with self.assertRaises(ValueError):
            driver.frame(99, 1)

    def test_rejects_out_of_range_values(self) -> None:
        with self.assertRaises(ValueError):
            driver.frame(driver.CMD_CPU_USAGE, 101)
        with self.assertRaises(ValueError):
            driver.frame(driver.CMD_CPU_TEMPERATURE, 65_535)
        with self.assertRaises(ValueError):
            driver.frame(driver.CMD_SHOW, -1)

    def test_rejects_non_finite_and_fractional_values(self) -> None:
        for value in (float("nan"), float("inf"), 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                driver.frame(driver.CMD_CPU_USAGE, value)


class WriteTests(unittest.TestCase):
    def test_writes_report_id_and_complete_report(self) -> None:
        report = driver.frame(driver.CMD_SHOW, 1)
        with mock.patch.object(driver.os, "write", return_value=65) as write:
            driver.write_report(7, report)
        write.assert_called_once_with(7, b"\x00" + report)

    def test_rejects_short_write(self) -> None:
        report = driver.frame(driver.CMD_SHOW, 1)
        with mock.patch.object(driver.os, "write", return_value=64):
            with self.assertRaises(driver.DriverError):
                driver.write_report(7, report)

    def test_rejects_wrong_report_length(self) -> None:
        with self.assertRaises(ValueError):
            driver.write_report(7, bytes(63))


class DeviceTests(unittest.TestCase):
    @staticmethod
    def _ioctl_identity(
        bus: int, vendor: int, product: int
    ) -> Callable[[int, int, bytearray, bool], int]:
        def fake_ioctl(
            _fd: int, request: int, buffer: bytearray, mutate: bool
        ) -> int:
            if request != driver.HIDIOCGRAWINFO or not mutate:
                raise AssertionError("unexpected ioctl call")
            buffer[:] = struct.pack("=IHH", bus, vendor, product)
            return 0

        return fake_ioctl

    @mock.patch.object(driver.os, "fstat")
    def test_accepts_expected_open_device(self, fstat: mock.MagicMock) -> None:
        fstat.return_value.st_mode = stat.S_IFCHR
        ioctl = self._ioctl_identity(
            driver.USB_BUS_TYPE, driver.USB_VENDOR_ID, driver.USB_PRODUCT_ID
        )
        with mock.patch.object(driver.fcntl, "ioctl", side_effect=ioctl):
            driver.verify_open_device(7, Path("/dev/hidraw7"))

    @mock.patch.object(driver.os, "fstat")
    def test_rejects_wrong_open_device(self, fstat: mock.MagicMock) -> None:
        fstat.return_value.st_mode = stat.S_IFCHR
        ioctl = self._ioctl_identity(driver.USB_BUS_TYPE, 0x1234, 0x5678)
        with mock.patch.object(driver.fcntl, "ioctl", side_effect=ioctl):
            with self.assertRaises(driver.DriverError):
                driver.verify_open_device(7, Path("/dev/hidraw7"))

    @mock.patch.object(driver.os, "fstat")
    def test_rejects_non_character_device(self, fstat: mock.MagicMock) -> None:
        fstat.return_value.st_mode = stat.S_IFREG
        with self.assertRaises(driver.DriverError):
            driver.verify_open_device(7, Path("/tmp/not-a-device"))


class SensorTests(unittest.TestCase):
    @staticmethod
    def _make_hwmon(root: Path, name: str, files: dict[str, str]) -> Path:
        hwmon = root / "hwmon0"
        hwmon.mkdir()
        _ = (hwmon / "name").write_text(name, encoding="ascii")
        for filename, value in files.items():
            _ = (hwmon / filename).write_text(value, encoding="ascii")
        return hwmon

    def test_selects_amd_tctl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hwmon = self._make_hwmon(
                root,
                "k10temp",
                {
                    "temp1_label": "Tdie\n",
                    "temp1_input": "60000\n",
                    "temp2_label": "Tctl\n",
                    "temp2_input": "65000\n",
                },
            )
            self.assertEqual(driver.find_temp_path(root), hwmon / "temp2_input")

    def test_selects_intel_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            hwmon = self._make_hwmon(
                root,
                "coretemp",
                {
                    "temp1_label": "Package id 0\n",
                    "temp1_input": "55000\n",
                },
            )
            self.assertEqual(driver.find_temp_path(root), hwmon / "temp1_input")

    def test_refuses_unrelated_sensor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._make_hwmon(root, "nvme", {"temp1_input": "45000\n"})
            with self.assertRaises(driver.DriverError):
                driver.find_temp_path(root)

    def test_reads_millidegrees(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            _ = fh.write("77500\n")
            path = Path(fh.name)
        try:
            self.assertEqual(driver.read_temp_c(path), 77.5)
        finally:
            path.unlink()

    def test_rejects_implausible_temperature(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as fh:
            _ = fh.write("999000\n")
            path = Path(fh.name)
        try:
            with self.assertRaises(ValueError):
                driver.read_temp_c(path)
        finally:
            path.unlink()

    def test_cpu_usage_does_not_double_count_guest_time(self) -> None:
        snapshots = (
            "cpu 100 0 0 100 0 0 0 0 50 0\n",
            "cpu 110 0 0 110 0 0 0 0 1050 0\n",
        )
        with (
            mock.patch.object(driver, "_read_text", side_effect=snapshots),
            mock.patch.object(driver.time, "sleep"),
        ):
            self.assertEqual(driver.read_cpu_usage(), 50.0)


class ArgumentTests(unittest.TestCase):
    def test_parser_populates_typed_namespace(self) -> None:
        args = driver.Arguments()
        _ = driver.build_argument_parser().parse_args(
            ["--metric", "usage", "--device", "/dev/hidraw7"], namespace=args
        )
        self.assertEqual(args.metric, "usage")
        self.assertEqual(args.device, Path("/dev/hidraw7"))
        self.assertIsNone(args.temp_path)

    def test_interval_rate_limit(self) -> None:
        self.assertEqual(driver.interval_arg("1"), 1.0)
        for value in ("0", "-1", "nan", "inf", "0.1"):
            with self.subTest(value=value), self.assertRaises(
                argparse.ArgumentTypeError
            ):
                driver.interval_arg(value)

    def test_wait_must_be_nonnegative(self) -> None:
        self.assertEqual(driver.nonnegative_int_arg("0"), 0)
        with self.assertRaises(argparse.ArgumentTypeError):
            driver.nonnegative_int_arg("-1")


if __name__ == "__main__":
    unittest.main()
