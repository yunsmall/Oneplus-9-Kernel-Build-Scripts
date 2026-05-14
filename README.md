# OnePlus Kernel Build Toolkit

一键创建一加内核编译目录/从 GitHub 下载源码并合并。

> 暂时只支持 OnePlus 9 (sm8350)。其他设备未测试。

## 已测试

| 设备 | 仓库 | 分支 |
|---|---|---|
| OnePlus 9 (sm8350) | `OnePlusOSS/android_kernel_oneplus_sm8350` | `oneplus/sm8350_u_14.0.0_oneplus9` |
| OnePlus 9 (sm8350) | `OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8350` | `oneplus/sm8350_u_14.0.0_oneplus9` |

## 文件说明

- `create_oneplus_build.py` — 主脚本，创建编译目录
- `gen_compile_commands.py` — 修改版，支持外部构建（新增 `-s` 指定源码树路径）
- `env.sh` — 由脚本自动生成在构建目录中，source 后设置好 CROSS_COMPILE / OUT_DIR 等

## 快速开始

```bash
# 自动下载并创建编译目录
./create_oneplus_build.py --download ~/oneplus_build

# 使用本地 zip
./create_oneplus_build.py modules.zip kernel.zip ~/oneplus_build

# 自定义仓库/分支
./create_oneplus_build.py --download ~/oneplus_build \
    --repo-kernel MyOrg/kernel --branch-kernel my-branch

# 仅打印编译教程（不执行构建）
./create_oneplus_build.py --guide ~/oneplus_build
```

## 获取 .config

```bash
# 从已 root 的手机提取
adb pull /proc/config.gz
gunzip config.gz
mv config ~/oneplus_build/out/.config
```

## 编译

```bash
# 脚本会在构建目录自动生成 env.sh，source 后所有变量就设好了
source ~/oneplus_build/env.sh

cd $KERNEL_DIR
mkdir -p $OUT_DIR

# 同步 .config 与内核版本
make O=$OUT_DIR olddefconfig

# 编译
make O=$OUT_DIR vmlinux -j$(nproc)
```

## 生成 compile_commands.json

```bash
python3 kernel/msm-5.4/scripts/gen_compile_commands.py \
    -d out -s kernel/msm-5.4
```
