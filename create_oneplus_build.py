#!/usr/bin/env python3
"""
一加内核编译目录创建脚本

支持两种模式：
  1. 本地 zip 模式：传入两个已下载的 zip 文件路径
  2. 下载模式 (--download)：自动从 GitHub 下载 zip

来源仓库（默认）：
  modules/devicetree:
    Repo:   https://github.com/OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8350
    Branch: oneplus/sm8350_u_14.0.0_oneplus9

  内核主源码:
    Repo:   https://github.com/OnePlusOSS/android_kernel_oneplus_sm8350
    Branch: oneplus/sm8350_u_14.0.0_oneplus9

用法：
  # 本地 zip
  python3 create_oneplus_build.py modules.zip kernel.zip /path/to/build

  # 从 GitHub 下载（使用默认仓库和分支）
  python3 create_oneplus_build.py --download /path/to/build

  # 自定义仓库和分支
  python3 create_oneplus_build.py --download /path/to/build \\
      --repo-kernel MyOrg/my-kernel-repo --branch-kernel my-branch

流程：
  1. 解压 modules/devicetree zip → 将 device/kernel/vendor/ 移到构建目录顶层
  2. 解压内核主源码 zip → 进入 kernel/msm-5.4/
  3. rsync -aH 将内核源码合并到 kernel/msm-5.4/（合并 techpack/ 等同名目录）
  4. 删除解压残留的空目录
  5. 修改顶层 Makefile：-Werror → -Wno-error（strict-prototypes, implicit-int）
  6. 输出编译命令
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request


# ---- GitHub archive URL helpers ----

def github_archive_url(repo, branch):
    """Return the GitHub archive download URL for a repo/branch.
    Example: github_archive_url('OnePlusOSS/android_kernel_oneplus_sm8350',
                                 'oneplus/sm8350_u_14.0.0_oneplus9')
    """
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


def download(url, dest_path):
    """Download a file with progress indicator."""
    print(f"  Downloading {url} ...")
    # Use wget for resumability and progress bar
    subprocess.run(
        ["wget", "-c", "--show-progress", "-O", dest_path, url],
        check=True,
    )


# ---- Utility ----

def run(cmd, cwd=None):
    print(f"  $ {cmd}")
    subprocess.run(cmd, shell=True, check=True, cwd=cwd)


def zip_toplevel(zip_path):
    """Return the top-level directory name inside a zip file."""
    out = subprocess.check_output(
        ["unzip", "-l", zip_path],
        stderr=subprocess.DEVNULL,
    ).decode()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "0":
            name = parts[-1]
            if name.endswith("/"):
                return name.rstrip("/")
    raise SystemExit(f"ERROR: could not find top-level dir in {zip_path}")


def apply_makefile_patches(kernel_dir):
    makefile = os.path.join(kernel_dir, "Makefile")
    print(f"\n  Patching {makefile}")
    with open(makefile) as f:
        content = f.read()
    patches = [
        ("-Werror=strict-prototypes", "-Wno-error=strict-prototypes"),
        ("-Werror=implicit-int", "-Wno-error=implicit-int"),
    ]
    for old, new in patches:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"    {old} -> {new}")
        else:
            print(f"    WARNING: '{old}' not found")
    with open(makefile, "w") as f:
        f.write(content)


# ---- Build steps ----

def build_from_zips(zip_modules, zip_source, build_dir, kernel_subdir):
    kernel_dir = os.path.join(build_dir, kernel_subdir)

    # Step 1
    print(f"\n[1/7] Creating {build_dir}")
    os.makedirs(build_dir, exist_ok=True)

    # Step 2
    print(f"\n[2/7] Unzipping modules_and_devicetree ...")
    top1 = zip_toplevel(zip_modules)
    run(f"unzip -q '{zip_modules}' -d '{build_dir}'")
    inner = os.path.join(build_dir, top1)
    for sub in os.listdir(inner):
        dst = os.path.join(build_dir, sub)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.move(os.path.join(inner, sub), build_dir)
    shutil.rmtree(inner)
    print(f"  Flattened and removed {top1}")

    # Step 3
    print(f"\n[3/7] Unzipping kernel source into {kernel_subdir} ...")
    os.makedirs(kernel_dir, exist_ok=True)
    top2 = zip_toplevel(zip_source)
    run(f"unzip -q '{zip_source}' -d '{kernel_dir}'")
    inner = os.path.join(kernel_dir, top2)

    # Step 4
    print(f"\n[4/7] Merging {top2}/* -> {kernel_subdir}/ via rsync -aH ...")
    run(f"rsync -aH '{inner}/' '{kernel_dir}/'")
    shutil.rmtree(inner)
    print(f"  Removed {top2}")

    # Step 5
    print(f"\n[5/7] Applying -Wno-error patches ...")
    apply_makefile_patches(kernel_dir)

    # Step 6: copy modified gen_compile_commands.py (supports -s source tree)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gcc_src = os.path.join(script_dir, "gen_compile_commands.py")
    gcc_dst = os.path.join(kernel_dir, "scripts", "gen_compile_commands.py")
    if os.path.exists(gcc_src):
        print(f"\n[6/7] Copying modified gen_compile_commands.py ...")
        shutil.copy2(gcc_src, gcc_dst)
        print(f"  {gcc_src} -> {gcc_dst}")

    # Step 7
    print(f"\n[7/7] Done!")
    print_build_info(build_dir, kernel_dir)


def print_build_info(build_dir, kernel_dir):
    print(f"""
{'=' * 60}
  Build directory: {build_dir}
  Kernel source:   {kernel_dir}

  --- 获取手机当前 .config ---

  # 方法 1: adb pull（推荐）
  adb pull /proc/config.gz
  gunzip config.gz
  mv config {build_dir}/out/.config

  # 方法 2: 在手机上操作，再 pull
  adb shell "cp /proc/config.gz /sdcard/config.gz"
  adb pull /sdcard/config.gz
  gunzip config.gz
  mv config {build_dir}/out/.config

  --- 同步 .config 与内核版本 ---

  cd {build_dir}
  mkdir -p out
  mv out/.config out/.config.bak
  make DISABLE_WRAPPER=1 LLVM=-20 O=out ARCH=arm64 olddefconfig

  --- 编译 ---

  make DISABLE_WRAPPER=1 LLVM=-20 O=out ARCH=arm64 vmlinux -j$(nproc)

  --- 生成 compile_commands.json ---

  python3 {kernel_dir}/scripts/gen_compile_commands.py \\
      -d {build_dir}/out -s {kernel_dir}
{'=' * 60}
""")


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description="一加内核编译目录创建脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 本地 zip 文件
  %(prog)s modules.zip kernel.zip /path/to/build

  # 从 GitHub 下载默认仓库（OnePlus 9, sm8350, Android 14）
  %(prog)s --download /path/to/build

  # 自定义仓库
  %(prog)s --download /path/to/build --repo-kernel MyOrg/kernel-repo

Source repos (defaults):
  modules/devicetree:
    OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8350 @ oneplus/sm8350_u_14.0.0_oneplus9
  kernel source:
    OnePlusOSS/android_kernel_oneplus_sm8350 @ oneplus/sm8350_u_14.0.0_oneplus9
""",
    )

    # Download mode
    parser.add_argument(
        "--download", action="store_true",
        help="从 GitHub 下载 zip（否则使用本地 zip 文件）",
    )
    parser.add_argument(
        "--repo-modules",
        default="OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8350",
        help="modules/devicetree 仓库 (default: OnePlusOSS/...)",
    )
    parser.add_argument(
        "--repo-kernel",
        default="OnePlusOSS/android_kernel_oneplus_sm8350",
        help="内核主源码仓库 (default: OnePlusOSS/...)",
    )
    parser.add_argument(
        "--branch-modules",
        default="oneplus/sm8350_u_14.0.0_oneplus9",
        help="modules/devicetree 分支 (default: oneplus/sm8350_u_14.0.0_oneplus9)",
    )
    parser.add_argument(
        "--branch-kernel",
        default="oneplus/sm8350_u_14.0.0_oneplus9",
        help="内核主源码分支 (default: oneplus/sm8350_u_14.0.0_oneplus9)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="下载缓存目录 (default: 系统临时目录)",
    )
    parser.add_argument(
        "--kernel-subdir", default="kernel/msm-5.4",
        help="内核在 build_dir 下的相对路径 (default: kernel/msm-5.4)",
    )

    # Positional args: zip paths and build dir
    parser.add_argument(
        "zip_modules_or_builddir",
        nargs="?",
        help="modules_and_devicetree.zip (本地模式) 或 build_dir (下载模式)",
    )
    parser.add_argument(
        "zip_source",
        nargs="?",
        help="内核主源码 .zip (仅本地模式)",
    )
    parser.add_argument(
        "build_dir_pos",
        nargs="?",
        help="编译目录路径 (仅本地模式)",
    )

    args = parser.parse_args()

    # ---- Display source info ----
    print("=" * 60)
    print("Source repositories:")
    print(f"  modules/devicetree:")
    print(f"    {args.repo_modules}")
    print(f"    branch: {args.branch_modules}")
    print(f"  kernel source:")
    print(f"    {args.repo_kernel}")
    print(f"    branch: {args.branch_kernel}")
    print("=" * 60)

    if args.download:
        # --- Download mode ---
        build_dir = os.path.abspath(args.zip_modules_or_builddir or ".")
        cache_dir = args.cache_dir or os.path.join(
            tempfile.gettempdir(), "oneplus_kernel_cache")

        url_modules = github_archive_url(args.repo_modules, args.branch_modules)
        url_kernel = github_archive_url(args.repo_kernel, args.branch_kernel)

        zip_modules = os.path.join(cache_dir, "modules.zip")
        zip_kernel = os.path.join(cache_dir, "kernel.zip")

        print(f"\nDownloading archives to {cache_dir} ...")
        os.makedirs(cache_dir, exist_ok=True)

        if not os.path.exists(zip_modules):
            download(url_modules, zip_modules)
        else:
            print(f"  Using cached {zip_modules}")

        if not os.path.exists(zip_kernel):
            download(url_kernel, zip_kernel)
        else:
            print(f"  Using cached {zip_kernel}")

        build_from_zips(zip_modules, zip_kernel, build_dir, args.kernel_subdir)

    else:
        # --- Local zip mode ---
        if not args.zip_modules_or_builddir or not args.zip_source or not args.build_dir_pos:
            parser.error(
                "本地模式需要三个参数: zip_modules zip_source build_dir\n"
                "或使用 --download 自动下载"
            )
        zip_modules = os.path.abspath(args.zip_modules_or_builddir)
        zip_source = os.path.abspath(args.zip_source)
        build_dir = os.path.abspath(args.build_dir_pos)
        build_from_zips(zip_modules, zip_source, build_dir, args.kernel_subdir)


if __name__ == "__main__":
    main()
