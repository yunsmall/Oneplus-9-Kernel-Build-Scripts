# OnePlus Kernel Build Toolkit

一键创建一加内核编译目录/从 GitHub 下载源码并合并。

> 暂时只支持 OnePlus 9 (sm8350)。其他设备未测试。

## 已测试

| 设备 | 仓库 | 分支 |
|---|---|---|
| OnePlus 9 (sm8350) | `OnePlusOSS/android_kernel_oneplus_sm8350` | `oneplus/sm8350_u_14.0.0_oneplus9` |
| OnePlus 9 (sm8350) | `OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8350` | `oneplus/sm8350_u_14.0.0_oneplus9` |

其他一加设备的仓库结构类似（一个内核仓库 + 一个 modules/devicetree 仓库），理论上可用，但未测试。

## 文件说明

- `create_oneplus_build.py` — 主脚本，创建编译目录
- `gen_compile_commands.py` — 修改版，支持外部构建（新增 `-s` 指定源码树路径）

## 快速开始

```bash
# 自动下载并创建编译目录
python3 create_oneplus_build.py --download ~/oneplus_build

# 使用本地 zip
python3 create_oneplus_build.py modules.zip kernel.zip ~/oneplus_build

# 自定义仓库/分支
python3 create_oneplus_build.py --download ~/oneplus_build \
    --repo-kernel MyOrg/kernel --branch-kernel my-branch
```

## 编译

```bash
cd ~/oneplus_build
mkdir -p out
make DISABLE_WRAPPER=1 LLVM=-20 O=out ARCH=arm64 vmlinux -j$(nproc)
```

## 生成 compile_commands.json

```bash
python3 kernel/msm-5.4/scripts/gen_compile_commands.py \
    -d out -s kernel/msm-5.4
```
