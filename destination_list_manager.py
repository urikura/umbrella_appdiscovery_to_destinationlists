import os
import requests
import json
import time
from dotenv import load_dotenv
from urllib.parse import urlparse
import logging

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# .env ファイルから環境変数を読み込み
load_dotenv()

# 環境変数から認証情報を取得
UMBRELLA_API_KEY = os.getenv("UMBRELLA_POLICIES_API_KEY")
UMBRELLA_API_SECRET = os.getenv("UMBRELLA_POLICIES_API_SECRET")

# API エンドポイント
AUTH_URL = "https://api.umbrella.com/auth/v2/token"
DESTINATION_LISTS_URL = "https://api.umbrella.com/policies/v2/destinationlists"

# 定数
MAX_DESTINATIONS_PER_REQUEST = 500  # APIの制限
REQUEST_DELAY = 0.2  # レート制限対応

def get_access_token():
    """OAuth 2.0 client credentials flowでアクセストークンを取得"""
    try:
        response = requests.post(
            AUTH_URL,
            auth=(UMBRELLA_API_KEY, UMBRELLA_API_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"}
        )
        response.raise_for_status()
        logger.info("✅ Access token obtained successfully")
        return response.json()["access_token"]
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error getting access token: {e}")
        if hasattr(e, 'response') and e.response:
            logger.error(f"Response: {e.response.text}")
        return None

def get_destination_lists(token):
    """既存のdestination listを取得"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(DESTINATION_LISTS_URL, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Found {len(data.get('data', []))} existing destination lists")
        return data.get('data', [])
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error getting destination lists: {e}")
        return []

def create_destination_list(token, name, access="block", list_type="domain"):
    """新しいdestination listを作成"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "name": name,
        "access": access,
        "isGlobal": False,
        "bundleTypeId": 1,
        "destinations": []
    }
    
    try:
        response = requests.post(DESTINATION_LISTS_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info(f"✅ Created destination list: {name} (ID: {result['data']['id']})")
        return result['data']
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error creating destination list {name}: {e}")
        if hasattr(e, 'response') and e.response:
            logger.error(f"Response: {e.response.text}")
        return None

def add_destinations_individually(token, list_id, destinations):
    """destination listに宛先を1つずつ追加（詳細なエラー情報取得）"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"{DESTINATION_LISTS_URL}/{list_id}/destinations"
    added_count = 0
    rejected_count = 0
    
    logger.info(f"Adding {len(destinations)} destinations individually for detailed error tracking...")
    
    for i, dest in enumerate(destinations):
        try:
            logger.info(f"Processing {i+1}/{len(destinations)}: {dest['destination']}")
            
            response = requests.post(url, headers=headers, json=[dest])
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Check if the response contains an error
                if response_data.get('statusCode') == 400:
                    error_msg = response_data.get('message', '')
                    logger.warning(f"  ❌ Rejected: {error_msg}")
                    rejected_count += 1
                else:
                    logger.info(f"  ✅ Added successfully")
                    added_count += 1
            else:
                logger.error(f"  ❌ HTTP Error {response.status_code}: {response.text}")
                rejected_count += 1
            
            # レート制限対応
            time.sleep(REQUEST_DELAY)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"  ❌ Request error: {e}")
            rejected_count += 1
    
    logger.info(f"📊 Individual processing summary:")
    logger.info(f"   Successfully added: {added_count}")
    logger.info(f"   Rejected/Failed: {rejected_count}")
    
    return added_count

def add_destinations_to_list(token, list_id, destinations):
    """destination listに宛先を追加（バッチ処理対応）"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    url = f"{DESTINATION_LISTS_URL}/{list_id}/destinations"
    added_count = 0
    rejected_count = 0
    
    # 500件ずつバッチ処理
    for i in range(0, len(destinations), MAX_DESTINATIONS_PER_REQUEST):
        batch = destinations[i:i + MAX_DESTINATIONS_PER_REQUEST]
        
        try:
            logger.info(f"Attempting to add batch {i//MAX_DESTINATIONS_PER_REQUEST + 1} with {len(batch)} destinations...")
            
            # Log a few sample destinations for debugging
            for j, dest in enumerate(batch[:3]):  # Show first 3 in batch
                logger.info(f"  Sample destination {j+1}: {dest['destination']} (type: {dest['type']})")
            
            response = requests.post(url, headers=headers, json=batch)
            
            # Log the response details
            logger.info(f"API Response Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"Response data: {json.dumps(response_data, indent=2)}")
                
                # Check if the response contains an error (statusCode: 400 within 200 response)
                if 'statusCode' in response_data and response_data.get('statusCode') == 400:
                    error_msg = response_data.get('message', '')
                    logger.warning(f"⚠️ API returned error: {error_msg}")
                    
                    # Parse individual rejection reasons if available
                    if '{' in error_msg and '}' in error_msg:
                        try:
                            # Extract JSON from error message
                            json_start = error_msg.find('{')
                            json_end = error_msg.rfind('}') + 1
                            error_json_str = error_msg[json_start:json_end]
                            # Unescape the JSON string
                            error_json_str = error_json_str.replace('\\"', '"').replace('\\/', '/')
                            error_details = json.loads(error_json_str)
                            
                            rejected_urls = list(error_details.keys())
                            rejected_count += len(rejected_urls)
                            added_count += len(batch) - len(rejected_urls)
                            
                            logger.warning(f"⚠️ {len(rejected_urls)} destinations rejected due to high-volume domains:")
                            for url, reason in error_details.items():
                                logger.warning(f"  - {url}: {reason}")
                            
                            if len(batch) > len(rejected_urls):
                                logger.info(f"✅ Successfully added {len(batch) - len(rejected_urls)} destinations from batch")
                        except json.JSONDecodeError:
                            # If we can't parse the error details, assume all were rejected
                            rejected_count += len(batch)
                            logger.warning(f"⚠️ All {len(batch)} destinations in batch were rejected")
                    else:
                        rejected_count += len(batch)
                        logger.warning(f"⚠️ All {len(batch)} destinations in batch were rejected")
                
                # Check if response contains successful status and destination count
                elif 'status' in response_data and response_data['status'].get('code') == 200:
                    # This is a successful response
                    if 'data' in response_data and 'meta' in response_data['data']:
                        # The response includes the updated destination count
                        new_count = response_data['data']['meta']['destinationCount']
                        logger.info(f"✅ Batch processed successfully. New destination count: {new_count}")
                        added_count += len(batch)  # Assume all were added unless we get specific error info
                    else:
                        # Fallback: assume all were added
                        added_count += len(batch)
                        logger.info(f"✅ Added {len(batch)} destinations to list (Total: {added_count}/{len(destinations)})")
                
                # Legacy check for 'data' list format (keeping for compatibility)
                elif 'data' in response_data and isinstance(response_data['data'], list):
                    actual_added = len(response_data['data'])
                    rejected_in_batch = len(batch) - actual_added
                    added_count += actual_added
                    rejected_count += rejected_in_batch
                    
                    if rejected_in_batch > 0:
                        logger.warning(f"⚠️ {rejected_in_batch} destinations were rejected in this batch")
                    
                    logger.info(f"✅ Successfully added {actual_added} destinations from batch (rejected: {rejected_in_batch})")
                else:
                    # Fallback: assume all were added if no specific response format matched
                    added_count += len(batch)
                    logger.info(f"✅ Added {len(batch)} destinations to list (Total: {added_count}/{len(destinations)})")
            else:
                logger.error(f"❌ API request failed with status {response.status_code}")
                logger.error(f"Response text: {response.text}")
                break
            
            # レート制限対応
            if i + MAX_DESTINATIONS_PER_REQUEST < len(destinations):
                time.sleep(REQUEST_DELAY)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error adding destinations batch {i//MAX_DESTINATIONS_PER_REQUEST + 1}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            
            # 高ボリュームドメインエラーの場合はログ出力して続行
            if "high-volume domain" in str(e):
                logger.warning("⚠️ Some URLs were on high-volume domains and were skipped")
                rejected_count += len(batch)
                continue
            else:
                break
    
    logger.info(f"📊 Batch Processing Summary:")
    logger.info(f"   Total destinations processed: {len(destinations)}")
    logger.info(f"   Successfully added: {added_count}")
    logger.info(f"   Rejected/Failed: {rejected_count}")
    
    # If batch processing had any errors or rejections, verify actual count and try individual processing
    if rejected_count > 0 or added_count < len(destinations):
        logger.warning("⚠️ Batch processing had errors or rejections. Verifying actual results...")
        
        # Get current destination count to verify actual additions
        headers = {"Authorization": f"Bearer {token}"}
        list_response = requests.get(f"{DESTINATION_LISTS_URL}/{list_id}", headers=headers)
        if list_response.status_code == 200:
            actual_count = list_response.json()['data']['meta']['destinationCount']
            logger.info(f"Actual destination count after batch processing: {actual_count}")
            
            # If no destinations were actually added, try individual processing
            if actual_count == 0:
                logger.warning("⚠️ No destinations were actually added. Trying individual processing...")
                individual_added = add_destinations_individually(token, list_id, destinations)
                
                # Check final count after individual processing
                final_response = requests.get(f"{DESTINATION_LISTS_URL}/{list_id}", headers=headers)
                if final_response.status_code == 200:
                    final_count = final_response.json()['data']['meta']['destinationCount']
                    logger.info(f"Final destination count after individual processing: {final_count}")
                    return final_count
                
                return individual_added
            else:
                logger.info(f"✅ Batch processing actually added {actual_count} destinations")
                return actual_count
    
    return added_count

def process_url(url):
    """URLを処理してdestination objectを作成"""
    if not url or not isinstance(url, str):
        return None
    
    # HTTPプロトコルが含まれていない場合は追加
    if not url.startswith(('http://', 'https://')):
        if url.startswith('www.'):
            url = f"https://{url}"
        else:
            # ドメインとして扱う
            return {
                "destination": url,
                "type": "domain",
                "comment": "Extracted from application URLs"
            }
    
    try:
        parsed = urlparse(url)
        
        # フルURLの場合
        if parsed.path and parsed.path != '/':
            return {
                "destination": url,
                "type": "url",
                "comment": "Extracted from application URLs"
            }
        # ドメインのみの場合
        else:
            return {
                "destination": parsed.netloc or parsed.path,
                "type": "domain",
                "comment": "Extracted from application URLs"
            }
    except Exception as e:
        logger.warning(f"⚠️ Could not parse URL: {url} - {e}")
        return None

def load_extracted_urls(filename="output_high.json"):
    """risk_app_extractor.pyが生成したURLデータを読み込み"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"Loaded URL data for {len(data)} applications from {filename}")
        return data
    except FileNotFoundError:
        logger.error(f"❌ File {filename} not found. Please run risk_app_extractor.py first with --collect-urls option.")
        return None
    except json.JSONDecodeError:
        logger.error(f"❌ Error reading {filename}. Please check the file format.")
        return None

def process_risk_level(access_token, risk_level):
    """指定されたリスクレベルのアプリケーションを処理"""
    filename = f"output_{risk_level.lower()}.json"
    list_name = f"{risk_level.title()} Risk Apps URLs"
    
    # URLデータを読み込み
    url_data = load_extracted_urls(filename)
    if not url_data:
        return False
    
    # 既存のdestination listを確認
    logger.info("Checking existing destination lists...")
    existing_lists = get_destination_lists(access_token)
    
    # URLを処理してdestination objectsを作成
    logger.info("Processing URLs...")
    all_destinations = []
    url_count = 0
    
    for app_name, app_data in url_data.items():
        urls = app_data.get('urls', [])
        app_id = app_data.get('app_id', 'unknown')
        
        for url in urls:
            dest_obj = process_url(url)
            if dest_obj:
                dest_obj['comment'] = f"From {risk_level.lower()} risk app: {app_name} (ID: {app_id})"
                all_destinations.append(dest_obj)
                url_count += 1
    
    logger.info(f"Processed {url_count} URLs into {len(all_destinations)} destination objects")
    
    if not all_destinations:
        logger.warning("⚠️ No valid destinations found to add")
        return False
    
    # Destination listを作成または選択
    destination_list = None
    
    # 既存のlistを確認
    for existing_list in existing_lists:
        if existing_list['name'] == list_name:
            destination_list = existing_list
            logger.info(f"Found existing destination list: {list_name} (ID: {destination_list['id']})")
            break
    
    # 新しいlistを作成
    if not destination_list:
        logger.info(f"Creating new destination list: {list_name}")
        destination_list = create_destination_list(access_token, list_name, "block")
        if not destination_list:
            return False
    
    # Destinationsを追加
    logger.info(f"Adding {len(all_destinations)} destinations to list...")
    added_count = add_destinations_to_list(access_token, destination_list['id'], all_destinations)
    
    logger.info(f"✅ {risk_level.title()} risk processing completed!")
    logger.info(f"   Destination List: {list_name} (ID: {destination_list['id']})")
    logger.info(f"   Total destinations processed: {len(all_destinations)}")
    logger.info(f"   Successfully added: {added_count}")
    
    if added_count < len(all_destinations):
        logger.warning(f"⚠️ {len(all_destinations) - added_count} destinations were not added (possibly due to high-volume domains or other restrictions)")
    
    return True

def process_file_directly(access_token, filename, list_name):
    """指定されたファイルを直接処理"""
    # URLデータを読み込み
    url_data = load_extracted_urls(filename)
    if not url_data:
        return False
    
    # 既存のdestination listを確認
    logger.info("Checking existing destination lists...")
    existing_lists = get_destination_lists(access_token)
    
    # URLを処理してdestination objectsを作成
    logger.info("Processing URLs...")
    all_destinations = []
    url_count = 0
    
    for app_name, app_data in url_data.items():
        urls = app_data.get('urls', [])
        app_id = app_data.get('app_id', 'unknown')
        
        for url in urls:
            dest_obj = process_url(url)
            if dest_obj:
                dest_obj['comment'] = f"From app: {app_name} (ID: {app_id})"
                all_destinations.append(dest_obj)
                url_count += 1
    
    logger.info(f"Processed {url_count} URLs into {len(all_destinations)} destination objects")
    
    if not all_destinations:
        logger.warning("⚠️ No valid destinations found to add")
        return False
    
    # Destination listを作成または選択
    destination_list = None
    
    # 既存のlistを確認
    for existing_list in existing_lists:
        if existing_list['name'] == list_name:
            destination_list = existing_list
            logger.info(f"Found existing destination list: {list_name} (ID: {destination_list['id']})")
            break
    
    # 新しいlistを作成
    if not destination_list:
        logger.info(f"Creating new destination list: {list_name}")
        destination_list = create_destination_list(access_token, list_name, "block")
        if not destination_list:
            return False
    
    # Destinationsを追加
    logger.info(f"Adding {len(all_destinations)} destinations to list...")
    added_count = add_destinations_to_list(access_token, destination_list['id'], all_destinations)
    
    logger.info(f"✅ File processing completed!")
    logger.info(f"   Destination List: {list_name} (ID: {destination_list['id']})")
    logger.info(f"   Total destinations processed: {len(all_destinations)}")
    logger.info(f"   Successfully added: {added_count}")
    
    if added_count < len(all_destinations):
        logger.warning(f"⚠️ {len(all_destinations) - added_count} destinations were not added (possibly due to high-volume domains or other restrictions)")
    
    return True

def main():
    """メイン処理"""
    import sys
    
    # 環境変数チェック
    if not all([UMBRELLA_API_KEY, UMBRELLA_API_SECRET]):
        logger.error("❌ Required environment variables not found in .env file:")
        logger.error("   UMBRELLA_POLICIES_API_KEY")
        logger.error("   UMBRELLA_POLICIES_API_SECRET")
        return
    
    # コマンドライン引数の処理
    risk_levels = []
    input_filename = None
    
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.endswith('.json'):
                # JSONファイルが指定された場合
                input_filename = arg
            elif arg.lower() in ['high', 'medium', 'low']:
                # リスクレベルが指定された場合
                risk_levels.append(arg.lower())
    
    # 引数がない場合はhighとmediumの両方を処理
    if not risk_levels and not input_filename:
        risk_levels = ['high', 'medium']
    
    # アクセストークンを取得
    logger.info("Getting access token...")
    access_token = get_access_token()
    if not access_token:
        return
    
    # ファイル名が直接指定された場合
    if input_filename:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing file: {input_filename}")
        logger.info(f"{'='*50}")
        
        # ファイル名からリスクレベルを推定
        if 'high' in input_filename.lower():
            list_name = "High Risk Apps URLs"
        elif 'medium' in input_filename.lower():
            list_name = "Medium Risk Apps URLs"
        elif 'low' in input_filename.lower():
            list_name = "Low Risk Apps URLs"
        else:
            list_name = f"Apps URLs from {input_filename}"
        
        if process_file_directly(access_token, input_filename, list_name):
            logger.info("✅ File processing completed successfully!")
        else:
            logger.error("❌ Failed to process file")
    else:
        # 各リスクレベルを処理
        success_count = 0
        for risk_level in risk_levels:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing {risk_level.upper()} risk applications...")
            logger.info(f"{'='*50}")
            
            if process_risk_level(access_token, risk_level):
                success_count += 1
            else:
                logger.error(f"❌ Failed to process {risk_level} risk applications")
        
        logger.info(f"\n{'='*50}")
        logger.info(f"✅ All processing completed!")
        logger.info(f"   Successfully processed: {success_count}/{len(risk_levels)} risk levels")
        logger.info(f"{'='*50}")

if __name__ == "__main__":
    main()
