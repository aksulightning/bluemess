import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('benchmark', Path(__file__).resolve().parents[1] / 'vm/benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def mem(available=716800, swapfree=0, swaptotal=0):
    return f'MemTotal: 1024000 kB\nMemAvailable: {available} kB\nSwapTotal: {swaptotal} kB\nSwapFree: {swapfree} kB\n'


class MemoryAcceptance(unittest.TestCase):
    def test_boundary_is_inclusive(self):
        self.assertEqual(benchmark.parse_meminfo(mem())['used_MiB'], '300')
        self.assertTrue(benchmark.parse_meminfo(mem())['accepted'])

    def test_one_kib_over_is_failure_without_rounding(self):
        result = benchmark.parse_meminfo(mem(716799))
        self.assertEqual(result['used_MiB'], '300.0009765625')
        self.assertFalse(result['accepted'])

    def test_swap_is_failure_even_with_low_ram(self):
        self.assertFalse(benchmark.parse_meminfo(mem(900000, 99, 100))['accepted'])

    def test_cannot_hide_failed_boot_with_average(self):
        readings = [benchmark.parse_meminfo(mem(900000)), benchmark.parse_meminfo(mem()), benchmark.parse_meminfo(mem(716799))]
        self.assertFalse(benchmark.summarize(readings)['accepted'])
        self.assertEqual(benchmark.summarize(readings)['maximum_MiB'], '300.0009765625')

    def test_incomplete_and_impossible_data_fail(self):
        for value in ('MemTotal: 100 kB', mem(2000000), mem(-1), mem(900000, 200, 100)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                benchmark.parse_meminfo(value)

    def test_requires_three_boots(self):
        with self.assertRaises(ValueError):
            benchmark.summarize([benchmark.parse_meminfo(mem())])


if __name__ == '__main__':
    unittest.main()
