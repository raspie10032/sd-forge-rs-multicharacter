# RS MultiCharacter for Forge Neo

**Windows 简便安装：** 完全退出 Forge Neo，然后 **[下载 BAT](https://github.com/raspie10032/sd-forge-rs-multicharacter/releases/download/v0.2.0a2/Install-RS-MultiCharacter.bat) → 运行 → 选择 Forge 目录**。无需 Git，自动安装／更新并备份旧扩展。[步骤与回退](docs/user-guide.zh-CN.md#windows-bat)。

**[安装步骤：URL、Git、ZIP、安装确认与更新](docs/user-guide.zh-CN.md#install)**

[한국어](README.ko.md) · [English](README.md) · [日本語](README.ja.md) · **简体中文**

**[用户指南：安装、双人练习与全部功能操作](docs/user-guide.zh-CN.md)** · [功能对照](docs/feature-parity.md) · [验证记录](docs/validation.md)

**在 Forge Neo 中组合角色独立提示词、区域、LoRA、参考图与姿势的扩展**。它将 [ComfyUI RS MultiCharacter Sampler](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler) 的区域 attention 及功能模块接入 Forge。

**当前版本为 `0.2.0a2` Alpha。** 训练后检查点的实际生成验证以 **Anima 2B** 为主。SD1.5、SDXL/Illustrious、FLUX、Krea 2、MOSS 也有执行路径，但小型随机权重模型的检查不能证明实际生成质量。扩展界面目前主要为韩文／英文，指南保留实际显示名称以便查找。

![Forge 双人生成示例](docs/images/two-character-example.png)

## 安装与使用

在 Forge **Extensions → Install from URL** 中输入地址，安装后重启 Forge。

```text
https://github.com/raspie10032/sd-forge-rs-multicharacter
```

[ZIP](https://github.com/raspie10032/sd-forge-rs-multicharacter/releases) 应解压为 `extensions/sd-forge-rs-multicharacter/scripts/`。基础生成无需额外依赖。已验证宿主为 Linux/Python 3.12、Forge Neo neo-2.31、提交 `4f4284b02a5c814b81c328c64ed7e99a139f21ef`。

1. 选择兼容的检查点、编码器与 VAE。
2. 打开 txt2img/img2img 的 **RS MultiCharacter · Forge Neo**，勾选 **멀티캐릭터 사용**。
3. Forge Positive 填写共享场景／背景，Negative 填写共享负面提示词。
4. 点击 **캐릭터 1 (프롬프트 입력)** 打开浮动窗，设置角色提示词、Point/Box、LoRA 及强度。**+ 캐릭터 추가** 可添加至最多 10 槽位。
5. Anima 可从 Precision / Euler a / SGM Uniform 开始。可复制的双人示例见[指南](docs/user-guide.zh-CN.md#quick-start)。

角色 LoRA 请在下拉框选择，不要在角色提示词中写 `<lora:...>`。

## 包含的功能

- 角色独立提示词与 LoRA，Point/Box，手绘／外部蒙版，身体部位强调与文字区域。
- Normal/Precision、分离及互动调度、相机条件、NovelAI 权重语法、渐进分辨率。
- 3D 关节／手指编辑、轮廓、姿势库、JSON/BVH/ZIP、图像→3D、学习式姿势引导。
- 参考图、SEGM/BBOX/SAM 细节修复、WD/PixAI 标签模型、本地文件夹批处理。
- Forge PNG／JSON 预设恢复、ComfyUI RS／NAI 设置交换。

可选权重在运行对应功能时准备，发布包不含模型。参考图与学习式姿势互斥等限制见[用户指南](docs/user-guide.zh-CN.md)与[功能表](docs/feature-parity.md)。不包含 App Mode 和角色独立负面提示词。

## 保存、恢复与限制

使用原始 PNG 的 **PNG Info → Send to txt2img/img2img**，或拖到 Positive 后点击 Forge 恢复按钮。JSON 是扩展配置预设。参考像素保存在 `models/rs_mc/assets/`，PNG 只记录 ID。换电脑需重新上传参考图，并准备模型／LoRA。

原版默认调度为 `0.05 / 1.7 / 0.9 / 3 / 0.2`，导入时以保存值为准。10 槽位不保证 10 人；人数增加时，两个应用都可能出现外观混合、人数缺失和角色分工错误。未证明独立完整生成的 PNG 像素一致，也未穷举附加组合、量化和其他操作系统。已验证宿主缺少 FLUX3 引擎，Nunchaku 不在支持范围内。

[验证与已知限制](docs/validation.md) · [技术设置](docs/advanced.md) · [开发](docs/development.md) · [GPL-3.0-only](COPYING) · [第三方许可](THIRD_PARTY_NOTICES.md)
