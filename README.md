# Umbrella Application Risk Management Tool

Cisco Umbrellaを使用してリスクレベル別のアプリケーションURLを含む宛先リストを作成するツールです。

## Setup

```bash
# リポジトリをクローン
git clone <repository-url>
cd <repository-dir>

# 仮想環境の有効化
source venv/bin/activate

# 依存関係をインストール
pip install -r requirements.txt

# API認証情報の設定
vi .env
# .envファイルに実際のAPI認証情報を設定
```

## Usage

```bash
# 1. アプリケーションの抽出
python3 risk_app_extractor.py "very high"
python3 risk_app_extractor.py "high"
python3 risk_app_extractor.py "medium"
python3 risk_app_extractor.py "low"
python3 risk_app_extractor.py "very low"

# 2. Destination Listの作成
python3 destination_list_manager.py output_very_high.json
python3 destination_list_manager.py output_high.json
python3 destination_list_manager.py output_medium.json
python3 destination_list_manager.py output_low.json
python3 destination_list_manager.py output_very_low.json
```

## Requirements

- Cisco Umbrella App Discovery API
- Cisco Umbrella Policies API v2

## Notes

- Google、Microsoft、Adobe等の高ボリュームドメインは自動除外されます
- 既存のDestination Listがある場合は重複をスキップします
- **このツールは検証目的で作成されています**
