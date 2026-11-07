# RS MultiCharacter for Forge Neo

**[インストール手順：URL・Git・ZIP、導入確認と更新](docs/user-guide.ja.md#install)**

[한국어](README.ko.md) · [English](README.md) · **日本語** · [简体中文](README.zh-CN.md)

**[ユーザーガイド：インストール・2人生成の練習・全機能の操作](docs/user-guide.ja.md)** · [機能比較](docs/feature-parity.md) · [検証記録](docs/validation.md)

**Forge Neo でキャラクター別のプロンプト、領域、LoRA、参照画像とポーズを組み合わせる拡張機能**です。[ComfyUI RS MultiCharacter Sampler](https://github.com/raspie10032/ComfyUI_RS_MultiCharacter_Sampler) の領域 attention と機能モジュールを Forge に接続しています。

**現在は `0.2.0a1` アルファ版です。** 実際のチェックポイントでの生成検証は **Anima 2B 中心**です。SD1.5、SDXL/Illustrious、FLUX、Krea 2、MOSS の実行経路もありますが、小さなランダム重みモデルによる検査は生成品質の検証ではありません。UI は現在主に韓国語／英語です。ガイドには実際の表示名を併記しています。

![Forge で生成した2人の例](docs/images/two-character-example.png)

## インストールと使い方

Forge の **Extensions → Install from URL** に入力し、インストール後に Forge を再起動します。

```text
https://github.com/raspie10032/sd-forge-rs-multicharacter
```

[ZIP](https://github.com/raspie10032/sd-forge-rs-multicharacter/releases) は `extensions/sd-forge-rs-multicharacter/scripts/` となるように展開します。基本生成に追加パッケージは不要です。検証ホストは Linux/Python 3.12、Forge Neo neo-2.31、コミット `4f4284b02a5c814b81c328c64ed7e99a139f21ef` です。

1. 対応チェックポイント、エンコーダー、VAE を選びます。
2. txt2img/img2img の **RS MultiCharacter · Forge Neo → 멀티캐릭터 사용** をオンにします。
3. Forge Positive に共通シーン・背景、Negative に共通ネガティブを入力します。
4. **캐릭터 1 (프롬프트 입력)** で浮動ウィンドウを開き、個別プロンプト、Point/Box、LoRA と強度を設定します。**+ 캐릭터 추가** で最大10スロットです。
5. Anima では Precision / Euler a / SGM Uniform から試せます。コピー可能な2人例は[ガイド](docs/user-guide.ja.md#quick-start)を参照してください。

LoRA はドロップダウンから選び、キャラクタープロンプトに `<lora:...>` を書かないでください。

## 含まれる機能

- キャラクター別プロンプト・LoRA、Point/Box、描画・外部マスク、部位強調、文字領域。
- Normal/Precision、分離・相互作用スケジュール、カメラ条件、NovelAI 重み構文、段階的解像度。
- 3D関節・指編集、シルエット、ポーズライブラリ、JSON/BVH/ZIP、画像→3D、学習済みポーズ。
- 参照画像、SEGM/BBOX/SAM ディテイラー、WD/PixAI タガー、ローカルフォルダー補正。
- Forge PNG/JSON プリセット復元、ComfyUI RS/NAI の設定交換。

追加モデルは該当機能の実行時に準備し、重みは同梱しません。参照と学習済みポーズの併用などには制限があります。[ユーザーガイド](docs/user-guide.ja.md)と[機能表](docs/feature-parity.md)で確認してください。App Mode・キャラクター別ネガティブは対象外です。

## 保存・復元と制限

元 PNG を **PNG Info → Send to txt2img/img2img** で送るか、Positive 欄にドロップして Forge の復元ボタンを押します。JSON は拡張設定のプリセットです。参照画素は `models/rs_mc/assets/` に保存され、PNG には ID のみ入ります。別 PC では参照を再アップロードし、モデル・LoRA も用意してください。

元の既定スケジュールは `0.05 / 1.7 / 0.9 / 3 / 0.2` です。保存設定が優先されます。10スロットは10人の保証ではなく、人数が増えると両アプリとも外見・人数・役割が崩れる場合があります。独立した全工程の PNG ピクセル一致、任意の追加機能併用、量子化、他 OS は未検証です。FLUX3 は検証ホストに実行エンジンがなく、Nunchaku は対象外です。

[検証と既知の制限](docs/validation.md) · [技術設定](docs/advanced.md) · [開発](docs/development.md) · [GPL-3.0-only](COPYING) · [第三者ライセンス](THIRD_PARTY_NOTICES.md)
