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
- `oneplus9_defconfig` — OnePlus 9 内核配置文件（从手机 `/proc/config.gz` 提取）
- `env.sh` — 由脚本自动生成在构建目录中，source 后设置好 CROSS_COMPILE / OUT_DIR 等

## CI 编译

本项目包含 GitHub Actions 工作流，Fork 后即可自动编译内核。

### 使用方法

1. **Fork 本项目**
2. **（可选）替换 `oneplus9_defconfig`** 为你自己手机的配置文件：

   **方法 A：Fork 后替换文件**
   ```bash
   adb pull /proc/config.gz
   gunzip config.gz
   mv config oneplus9_defconfig
   git add oneplus9_defconfig && git commit && git push
   ```

   **方法 B：通过 Gist 传入（不修改仓库）**
   ```bash
   # 上传 config 到 Gist
   adb pull /proc/config.gz
   gunzip config.gz
   gh gist create config --public   # 或 --secret 创建私有 Gist
   # 拿到 raw URL: https://gist.githubusercontent.com/.../raw/.../config
   ```
   CI 触发时在 `config_url` 填入 Gist raw URL 即可。

3. 手动触发 CI：`Actions` → `Build Kernel` → `Run workflow`，可选填入 `config_url`
4. 等待编译完成，下载产物（vmlinux、Image、modules.squashfs）

### CI 产物使用

三种产物分别对应：

- **vmlinux** — 带符号的内核 ELF，可用于调试
- **Image** — 压缩内核镜像（Image.gz），用于替换系统内核
- **modules** — 模块 squashfs 只读压缩镜像

替换内核后，需同步替换模块。**不要直接 mount 到 /lib/modules**（会覆盖系统中其他内核版本的模块）。正确做法：

```bash
# 获取内核版本号
KVER=$(zcat /proc/config.gz | grep '^CONFIG_LOCALVERSION' | cut -d'"' -f2)

# 挂载模块镜像
mount modules.squashfs /mnt/modules
ln -s /mnt/modules/lib/modules/$KVER /lib/modules/$KVER
```

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

项目已自带 `oneplus9_defconfig`（从 OnePlus 9 提取）。如需使用自己手机的配置：

```bash
# 从已 root 的手机提取
adb pull /proc/config.gz
gunzip config.gz
mv config oneplus9_defconfig
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
