"""Command-line entry for known-password decryption only."""

import argparse
from pathlib import Path
import sys

from pdfunlock.batch import decrypt_file, prepare_output_directory


def build_parser():
    parser = argparse.ArgumentParser(prog="pdfunlock", description="PDF 已知密码解密 / 去除限制工具")
    parser.add_argument("-f", "--file", required=True, help="PDF 文件路径")
    parser.add_argument("-m", "--mode", required=True,
                        choices=["SinglePassword", "RemoveRestrictions"], help="使用已知密码，或处理无打开密码的文件")
    parser.add_argument("-p", "--password", default="", help="已知的 PDF 密码")
    parser.add_argument("-o", "--output-dir", help="导出目录，默认与源文件相同")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    source = Path(args.file)
    if not source.is_file():
        print(f"错误：文件不存在 - {source}")
        return 2
    try:
        destination = prepare_output_directory(args.output_dir or source.parent)
    except (OSError, ValueError):
        print("错误：无法写入导出目录，请检查路径、权限与磁盘空间。")
        return 2
    passwords = [args.password] if args.mode == "SinglePassword" else []
    result = decrypt_file(source, passwords, destination)
    if result.status != "success":
        print(f"错误：{result.message}")
        return 1
    print(f"{result.message}，保存为：{result.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
