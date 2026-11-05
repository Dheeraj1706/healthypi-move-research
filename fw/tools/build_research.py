"""Build with Python from a Nordic toolchain environment; never flashes a device."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-root', type=Path, required=True)
    parser.add_argument('--pristine', action='store_true')
    options = parser.parse_args()
    fw = Path(__file__).resolve().parents[1]
    sdk = options.sdk_root.resolve()
    if not (sdk / '.west').is_dir():
        parser.error('--sdk-root must contain the installed SDK .west directory')
    log = fw.parent / 'output/firmware/nordic_build.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, '-m', 'west', 'build', str(fw / 'app'),
            '--build-dir', str(fw / 'build'),
            '--board', 'healthypi_move/nrf5340/cpuapp']
    if options.pristine:
        args.append('--pristine')
    args += ['--', '-DNCS_TOOLCHAIN_VERSION=NONE',
             '-DBOARD_ROOT=' + fw.as_posix(),
             '-DZEPHYR_EXTRA_MODULES=' + fw.as_posix()]
    # Keep each CMake path in a single argument through the Windows launcher.
    with log.open('w', encoding='utf-8') as output:
        proc = subprocess.Popen(args, cwd=sdk, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace')
        for line in proc.stdout:
            output.write(line)
            output.flush()
            print(line, end='', flush=True)
        return proc.wait()


if __name__ == '__main__':
    sys.exit(main())
