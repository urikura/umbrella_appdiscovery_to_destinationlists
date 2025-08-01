import requests
import json
import argparse # Import argparse library
import time
import os
from urllib.parse import urlparse, urljoin
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
# Get API credentials from environment variables
CLIENT_ID = os.getenv("UMBRELLA_APP_DISCOVERY_API_KEY")
CLIENT_SECRET = os.getenv("UMBRELLA_APP_DISCOVERY_API_SECRET")

# API Endpoints
AUTH_URL = "https://api.umbrella.com/auth/v2/token"
API_URL = "https://api.umbrella.com/reports/v2/appDiscovery/applications"
APP_DETAIL_URL = "https://api.umbrella.com/reports/v2/appDiscovery/applications/{app_id}"

# --- Functions ---

def get_access_token():
    """
    Retrieves an access token from the Cisco Umbrella API.
    """
    try:
        response = requests.post(
            AUTH_URL,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={"grant_type": "client_credentials"}
        )
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()["access_token"]
    except requests.exceptions.RequestException as e:
        print(f"Error getting access token: {e}")
        return None

def get_all_applications(token):
    """
    Retrieves all applications from the App Discovery API, handling pagination.
    """
    all_apps = []
    page = 1
    total_pages = 1

    headers = {
        "Authorization": f"Bearer {token}"
    }

    while page <= total_pages:
        try:
            params = {'page': page, 'limit': 100}
            response = requests.get(API_URL, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_apps.extend(data.get("items", []))
            total_pages = data.get("totalPages", 1)
            print(f"Fetched page {page} of {total_pages}")
            page += 1

        except requests.exceptions.RequestException as e:
            print(f"Error fetching applications: {e}")
            break
            
    return all_apps

def get_application_details(token, app_id):
    """
    特定のアプリケーションの詳細情報を取得する
    """
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    try:
        url = APP_DETAIL_URL.format(app_id=app_id)
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching details for app {app_id}: {e}")
        return None

def extract_urls_from_app_data(app_data):
    """
    アプリケーションデータからURLを再帰的に抽出する
    """
    urls = set()
    
    def recursive_url_search(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                
                # URLらしきキーをチェック
                if any(url_key in key.lower() for url_key in ['url', 'uri', 'link', 'href', 'endpoint', 'domain']):
                    if isinstance(value, str) and (value.startswith('http') or value.startswith('www.')):
                        urls.add(value)
                        print(f"Found URL in {current_path}: {value}")
                
                # 値がURLらしきものかチェック
                if isinstance(value, str):
                    if value.startswith('http://') or value.startswith('https://'):
                        urls.add(value)
                        print(f"Found URL in {current_path}: {value}")
                    elif value.startswith('www.') and '.' in value:
                        urls.add(f"https://{value}")
                        print(f"Found domain in {current_path}: {value} (converted to https://{value})")
                
                # 再帰的に探索
                recursive_url_search(value, current_path)
                
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path = f"{path}[{i}]" if path else f"[{i}]"
                recursive_url_search(item, current_path)
    
    recursive_url_search(app_data)
    return list(urls)

def collect_urls_from_apps(token, input_filename, output_filename=None):
    """
    指定されたJSONファイルのアプリケーションからURLを収集する
    """
    try:
        # JSONファイルを読み込む
        with open(input_filename, 'r') as f:
            apps = json.load(f)
        
        print(f"Found {len(apps)} applications in {input_filename}")
        
        all_urls = {}
        
        for i, app in enumerate(apps):
            app_id = app.get('id')
            app_name = app.get('name', 'Unknown')
            
            print(f"\nProcessing app {i+1}/{len(apps)}: {app_name} (ID: {app_id})")
            
            # まず現在のアプリデータからURLを抽出
            urls_from_current = extract_urls_from_app_data(app)
            
            # APIから詳細情報を取得
            app_details = get_application_details(token, app_id)
            if app_details:
                urls_from_details = extract_urls_from_app_data(app_details)
                all_urls_for_app = list(set(urls_from_current + urls_from_details))
            else:
                all_urls_for_app = urls_from_current
            
            if all_urls_for_app:
                all_urls[app_name] = {
                    'app_id': app_id,
                    'urls': all_urls_for_app,
                    'url_count': len(all_urls_for_app)
                }
                print(f"  → Found {len(all_urls_for_app)} URLs for {app_name}")
            else:
                print(f"  → No URLs found for {app_name}")
            
            # APIレート制限を避けるため少し待機
            time.sleep(0.1)
        
        # 出力ファイル名を決定
        if not output_filename:
            base_name = input_filename.replace('.json', '')
            output_filename = f"{base_name}_urls.json"
        
        # URLリストをファイルに保存
        with open(output_filename, 'w') as f:
            json.dump(all_urls, f, indent=4)
        
        print(f"\n✅ URL collection completed! Results saved to {output_filename}")
        print(f"Total apps with URLs: {len(all_urls)}")
        
        # 統計情報を表示
        total_urls = sum(app_data['url_count'] for app_data in all_urls.values())
        print(f"Total URLs found: {total_urls}")
        
        return all_urls
        
    except FileNotFoundError:
        print(f"❌ {input_filename} file not found. Please run the script to get application data first.")
        return None
    except json.JSONDecodeError:
        print(f"❌ Error reading {input_filename} file. Please check the file format.")
        return None

def collect_urls_from_medium_apps(token):
    """
    medium.jsonのアプリケーションからURLを収集する
    """
    try:
        # medium.jsonファイルを読み込む
        with open('medium.json', 'r') as f:
            medium_apps = json.load(f)
        
        print(f"Found {len(medium_apps)} medium risk applications")
        
        all_urls = {}
        
        for i, app in enumerate(medium_apps):
            app_id = app.get('id')
            app_name = app.get('name', 'Unknown')
            
            print(f"\nProcessing app {i+1}/{len(medium_apps)}: {app_name} (ID: {app_id})")
            
            # まず現在のアプリデータからURLを抽出
            urls_from_current = extract_urls_from_app_data(app)
            
            # APIから詳細情報を取得
            app_details = get_application_details(token, app_id)
            if app_details:
                urls_from_details = extract_urls_from_app_data(app_details)
                all_urls_for_app = list(set(urls_from_current + urls_from_details))
            else:
                all_urls_for_app = urls_from_current
            
            if all_urls_for_app:
                all_urls[app_name] = {
                    'app_id': app_id,
                    'urls': all_urls_for_app,
                    'url_count': len(all_urls_for_app)
                }
                print(f"  → Found {len(all_urls_for_app)} URLs for {app_name}")
            else:
                print(f"  → No URLs found for {app_name}")
            
            # APIレート制限を避けるため少し待機
            time.sleep(0.1)
        
        # URLリストをファイルに保存
        output_filename = "medium_apps_urls.json"
        with open(output_filename, 'w') as f:
            json.dump(all_urls, f, indent=4)
        
        print(f"\n✅ URL collection completed! Results saved to {output_filename}")
        print(f"Total apps with URLs: {len(all_urls)}")
        
        # 統計情報を表示
        total_urls = sum(app_data['url_count'] for app_data in all_urls.values())
        print(f"Total URLs found: {total_urls}")
        
        return all_urls
        
    except FileNotFoundError:
        print("❌ medium.json file not found. Please run the script with 'medium' risk level first.")
        return None
    except json.JSONDecodeError:
        print("❌ Error reading medium.json file. Please check the file format.")
        return None

def filter_and_save_apps(apps, risk_level, filename):
    """
    Filters applications by risk level and saves them to a JSON file.
    """
    # Use case-insensitive matching for the risk level
    filtered_apps = [
        app for app in apps 
        if app.get("weightedRisk", "").lower() == risk_level.lower()
    ]

    with open(filename, 'w') as f:
        json.dump(filtered_apps, f, indent=4)
    
    print(f"✅ Successfully saved {len(filtered_apps)} applications with '{risk_level}' risk to {filename}")


# --- Main Execution ---

if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Fetch Cisco Umbrella applications and filter by risk level, or collect URLs from medium risk apps."
    )
    parser.add_argument(
        "risk_level", 
        type=str,
        nargs='?',  # オプション引数にする
        help="The risk level to filter for (e.g., 'low', 'medium', 'high', 'very high'), or use 'collect-urls' to collect URLs from medium.json."
    )
    parser.add_argument(
        "--collect-urls",
        action="store_true",
        help="Collect URLs from applications in medium.json file"
    )
    parser.add_argument(
        "--input-file",
        type=str,
        help="Input JSON file to collect URLs from (e.g., high.json, medium.json)"
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Output JSON file name for URL collection results"
    )
    args = parser.parse_args()
    
    # --- Script Logic ---
    if not CLIENT_ID or not CLIENT_SECRET:
        print("🛑 Please set UMBRELLA_APP_DISCOVERY_API_KEY and UMBRELLA_APP_DISCOVERY_API_SECRET in your .env file.")
        print("Example .env file content:")
        print("UMBRELLA_APP_DISCOVERY_API_KEY=your_client_id")
        print("UMBRELLA_APP_DISCOVERY_API_SECRET=your_client_secret")
        exit(1)
    
    print("Getting access token...")
    access_token = get_access_token()
    if access_token:
        # URL収集モードの場合
        if args.collect_urls or (args.risk_level and args.risk_level.lower() == "collect-urls"):
            if args.input_file:
                # 指定されたファイルからURL収集
                print(f"Starting URL collection from {args.input_file}...")
                collect_urls_from_apps(access_token, args.input_file, args.output_file)
            else:
                # デフォルトでmedium.jsonからURL収集
                print("Starting URL collection from medium risk applications...")
                collect_urls_from_medium_apps(access_token)
        # 通常のアプリケーション取得モードの場合
        elif args.risk_level:
            print("Fetching applications...")
            applications = get_all_applications(access_token)
            if applications:
                # Get risk level from arguments and create filenames
                risk_to_filter = args.risk_level
                intermediate_filename = f"{risk_to_filter.replace(' ', '_')}.json"
                output_filename = f"output_{risk_to_filter.replace(' ', '_')}.json"

                print(f"Filtering for '{risk_to_filter}' risk applications...")
                filter_and_save_apps(applications, risk_to_filter, intermediate_filename)
                
                # 直接URL収集を実行
                print(f"Collecting URLs from {risk_to_filter} risk applications...")
                collect_urls_from_apps(access_token, intermediate_filename, output_filename)
                
                # 中間ファイルを削除
                import os
                if os.path.exists(intermediate_filename):
                    os.remove(intermediate_filename)
                    print(f"✅ Cleaned up intermediate file: {intermediate_filename}")
        else:
            print("Please specify a risk level or use --collect-urls option")
            print("Examples:")
            print("  python risk_app_extractor.py medium")
            print("  python risk_app_extractor.py --collect-urls")
            print("  python risk_app_extractor.py collect-urls")
            print("  python risk_app_extractor.py --collect-urls --input-file high.json --output-file output_medium.json")