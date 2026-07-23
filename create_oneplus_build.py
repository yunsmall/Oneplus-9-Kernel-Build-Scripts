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
  5. 修改顶层 Makefile：-Werror=strict-prototypes → -Wno-error=strict-prototypes
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
        ("-Wno-format-security",
         "-Wno-format-security -Wno-error=vla-extension"),
    ]
    for old, new in patches:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"    {old} -> {new}")
        else:
            print(f"    WARNING: '{old}' not found")
    with open(makefile, "w") as f:
        f.write(content)


def apply_nfs_kconfig_patches(kernel_dir):
    """Change NFS_V3/NFS_V4 from bool to tristate so they can be compiled as modules."""
    kconfig = os.path.join(kernel_dir, "fs", "nfs", "Kconfig")
    print(f"\n  Patching {kconfig}")
    with open(kconfig) as f:
        content = f.read()
    patches = [
        ('bool "NFS client support for NFS version 3"',
         'tristate "NFS client support for NFS version 3"'),
        ('bool "NFS client support for NFS version 4"',
         'tristate "NFS client support for NFS version 4"'),
    ]
    for old, new in patches:
        if old in content:
            content = content.replace(old, new, 1)
            print(f"    bool -> tristate")
        else:
            print(f"    WARNING: NFS Kconfig patch not found")
    with open(kconfig, "w") as f:
        f.write(content)


def generate_env_sh(build_dir, kernel_dir, llvm="1"):
    """Generate env.sh in the build directory."""
    env_sh = os.path.join(build_dir, "env.sh")
    print(f"  Writing {env_sh}")
    with open(env_sh, "w") as f:
        f.write(f"""\
# OnePlus kernel build environment
# Usage: source env.sh

export ARCH=arm64
export LLVM={llvm}
export DISABLE_WRAPPER=1
export CLANG_TRIPLE=aarch64-linux-gnu-
export CROSS_COMPILE=aarch64-linux-android-

export BUILD_DIR={build_dir}
export KERNEL_DIR={kernel_dir}
export OUT_DIR={build_dir}/out

echo "Environment:"
echo "  ARCH=$ARCH"
echo "  LLVM=$LLVM"
echo "  DISABLE_WRAPPER=$DISABLE_WRAPPER"
echo "  CLANG_TRIPLE=$CLANG_TRIPLE"
echo "  CROSS_COMPILE=$CROSS_COMPILE"
echo "  BUILD_DIR=$BUILD_DIR"
echo "  KERNEL_DIR=$KERNEL_DIR"
echo "  OUT_DIR=$OUT_DIR"
echo ""
echo "Now you can run:"
echo "  cd $KERNEL_DIR"
echo "  make O=$OUT_DIR olddefconfig"
echo "  make O=$OUT_DIR vmlinux -j\\\\$(nproc)"
""")
    os.chmod(env_sh, 0o755)


# ---- Build steps ----

def build_from_zips(zip_modules, zip_source, build_dir, kernel_subdir, llvm="1"):
    kernel_dir = os.path.join(build_dir, kernel_subdir)

    # Pre-compute values needed by steps
    top1 = zip_toplevel(zip_modules)
    top2 = zip_toplevel(zip_source)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gcc_src = os.path.join(script_dir, "gen_compile_commands.py")
    gcc_dst = os.path.join(kernel_dir, "scripts", "gen_compile_commands.py")

    steps = [
        (f"Creating {build_dir}",
         lambda: os.makedirs(build_dir, exist_ok=True)),

        ("Unzipping modules_and_devicetree ...",
         lambda: _step_unzip_modules(zip_modules, build_dir, top1)),

        (f"Unzipping kernel source into {kernel_subdir} ...",
         lambda: _step_unzip_kernel(zip_source, kernel_dir, top2)),

        (f"Merging {top2}/* -> {kernel_subdir}/ via rsync -aH ...",
         lambda: _step_merge_kernel(kernel_dir, top2)),

        ("Applying source patches ...",
         lambda: _step_patches(kernel_dir)),

        ("Generating env.sh ...",
         lambda: generate_env_sh(build_dir, kernel_dir, llvm)),

        ("Copying modified gen_compile_commands.py ...",
         lambda: _step_copy_gcc(gcc_src, gcc_dst)),
    ]

    total = len(steps)
    for i, (desc, action) in enumerate(steps, 1):
        print(f"\n[{i}/{total}] {desc}")
        action()

    print(f"\n[{total}/{total}] Done!")
    print_build_info(build_dir, kernel_dir)


def _step_unzip_modules(zip_modules, build_dir, top1):
    run(f"unzip -q '{zip_modules}' -d '{build_dir}'")
    inner = os.path.join(build_dir, top1)
    for sub in os.listdir(inner):
        dst = os.path.join(build_dir, sub)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.move(os.path.join(inner, sub), build_dir)
    shutil.rmtree(inner)
    print(f"  Flattened and removed {top1}")


def _step_unzip_kernel(zip_source, kernel_dir, top2):
    os.makedirs(kernel_dir, exist_ok=True)
    run(f"unzip -q '{zip_source}' -d '{kernel_dir}'")


def _step_merge_kernel(kernel_dir, top2):
    inner = os.path.join(kernel_dir, top2)
    run(f"rsync -aH '{inner}/' '{kernel_dir}/'")
    shutil.rmtree(inner)
    print(f"  Removed {top2}")


def _step_patches(kernel_dir):
    apply_makefile_patches(kernel_dir)
    apply_nfs_kconfig_patches(kernel_dir)


def _step_copy_gcc(gcc_src, gcc_dst):
    if os.path.exists(gcc_src):
        shutil.copy2(gcc_src, gcc_dst)
        print(f"  {gcc_src} -> {gcc_dst}")


def print_build_info(build_dir, kernel_dir):
    kr = os.path.relpath(kernel_dir, build_dir)
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

  --- 设置环境 ---

  source {build_dir}/env.sh

  --- 同步 .config 与内核版本 ---
  # 注意：O= 必须使用绝对路径，否则 make -C 会把 out 创建在内核源码目录里

  cd {build_dir}
  mkdir -p out
  cp out/.config out/.config.bak   # 备份旧 .config（如果有）
  make -C {kr} O={build_dir}/out olddefconfig

  # 可选：如需进一步调整内核配置（比如开启/关闭某些模块）
  make -C {kr} O={build_dir}/out menuconfig

  --- 编译 ---

  make -C {kr} O={build_dir}/out vmlinux -j$(nproc)

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
    parser.add_argument(
        "--llvm", default="1",
        help="LLVM 版本，如 1（默认）、-20、-18 (default: 1)",
    )
    parser.add_argument(
        "--guide", action="store_true",
        help="仅打印编译教程（不执行构建）",
    )
    parser.add_argument(
        "--env-only", action="store_true",
        help="仅生成 env.sh（不执行构建）",
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

    # --guide: just print build instructions and exit
    if args.guide:
        build_dir = os.path.abspath(args.zip_modules_or_builddir or os.getcwd())
        kernel_dir = os.path.join(build_dir, args.kernel_subdir)
        print_build_info(build_dir, kernel_dir)
        return

    # --env-only: just generate env.sh and exit
    if args.env_only:
        build_dir = os.path.abspath(args.zip_modules_or_builddir or os.getcwd())
        kernel_dir = os.path.join(build_dir, args.kernel_subdir)
        print(f"Generating env.sh in {build_dir} ...")
        generate_env_sh(build_dir, kernel_dir, args.llvm)
        print("Done.")
        return

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

        build_from_zips(zip_modules, zip_kernel, build_dir, args.kernel_subdir, args.llvm)

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
