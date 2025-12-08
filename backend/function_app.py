import azure.functions as func  # type: ignore
import pymupdf  # type: ignore
from openai import AzureOpenAI  # type: ignore
 
import os
from io import BytesIO
import logging
import tempfile
import base64
import json
from urllib.parse import urlparse
from PIL import Image  # type: ignore
 
from azure.storage.blob import BlobServiceClient  # type: ignore
 
from service.openai_service.openai_service import AzureOpenAIService
from service.cosmos_service.cosmos_service import CosmosService
from domain.object_cosmos_page import CosmosPageObj # type: ignore
from domain.document_structure import DocumentStructure
 
logging.basicConfig(level=logging.INFO)
app = func.FunctionApp()
 
STR_AI_SYSTEMMESSAGE = """
##制約条件
- 画像内の情報を、Markdown形式に整理しなさい。
- 図や表が含まれる場合、図や表の内容を理解できるように説明する文章にしなさい。
- 回答形式 以外の内容は記載しないでください。
- 回答の最初に「```json」を含めないこと。
 
##回答形式##
{
    "content":"画像をテキストに変換した文字列",
    "keywords": "カンマ区切りのキーワード群",
    "is_contain_image": "図や表などの画像で保存しておくべき情報が含まれている場合はtrue、それ以外はfalse"
}
 
##記載情報##
- content: 画像内の情報はcontentに記載してください。画像内の情報を漏れなく記載してください。
- keywords: 画像内の情報で重要なキーワードをkeywordsに記載してください。カンマ区切りで複数記載可能です。
- is_contain_image: 図や表などの画像で保存しておくべき情報が含まれている場合はtrue、それ以外はfalseを記載してください。
"""
STR_AI_USERMESSAGE = """画像の内容を用いて回答しなさい。Json形式でのみ回答してください。"""
STR_SAMPLE_USERMESSAGE = """画像の内容を用いて回答しなさい。Json形式でのみ回答してください。"""
STR_SAMPLE_AIRESPONSE = """{
    "content":"画像をテキストに変換した文字列",
    "keywords": "word1, word2, word3"
}"""
 
BLOB_TRIGGER_PATH = "rag-docs"
 
BLOB_CONTAINER_NAME_IMAGE = "rag-images"
BLOB_CONNECTION = os.getenv("BLOB_CONNECTION")
 
 
@app.event_grid_trigger(arg_name="azeventgrid")
def EventGridTrigger(azeventgrid: func.EventGridEvent):
    event = json.dumps({
        'id': azeventgrid.id,
        'data': azeventgrid.get_json(),
        'topic': azeventgrid.topic,
        'subject': azeventgrid.subject,
        'event_type': azeventgrid.event_type,
    })
    event_dict = json.loads(event)  # eventを辞書型に変換
    blob_url = event_dict.get("data").get("url")
 
    logging.info('🚀 Python EventGrid trigger processed an event')
    logging.info(f"🚀 azeventgrid.get_json() : {azeventgrid.get_json()}")
 
    aoai_client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version="2024-08-01-preview"  # 2024-08-01-preview
    )
    azure_openai_service = AzureOpenAIService(client=aoai_client)
    cosmos_service = CosmosService()
    blob_service_client = BlobServiceClient.from_connection_string(
        BLOB_CONNECTION)
 
    try:
        # event_typeがMicrosoft.Storage.BlobCreatedの場合
        if event_dict.get("event_type") == "Microsoft.Storage.BlobCreated":
 
            logging.info(f"🚀Event Type: {event_dict.get('event_type')}")
 
            # Blobのファイルパスを取得
            blob_file_path = blob_url.split(f"{BLOB_TRIGGER_PATH}/")[1]
            logging.info(f"🚀Blob File Path: {blob_file_path}")
            blob_client = blob_service_client.get_blob_client(
                container=BLOB_TRIGGER_PATH, blob=blob_file_path)
            blob_data = blob_client.download_blob()
            logging.info(f"🚀Blob File downloaded.")
 
            # Blobからダウンロードしたファイルのファイル名と拡張子を取得
            file_name = blob_data.name
            file_extension = os.path.splitext(file_name)[1]
 
            logging.info(f"🚀Blob Data: {blob_data}")
            logging.info(f"🚀Blob Name: {file_name}")
            logging.info(f"🚀Blob Extension: {file_extension}")
 
            ragdocs = blob_data.content_as_bytes()
            data_as_file = BytesIO(ragdocs)
 
            # 同じfile_nameがCosmosDBに存在する場合は、そのアイテムを削除する
            query = f"SELECT * FROM c WHERE c.file_name = \"{file_name}\""
            items = cosmos_service.get_data(query)
            for item in items:
                cosmos_service.delete_data(item["id"])
                logging.info(
                    f"🚀Deleted data from CosmosDB: {item['file_name']}, {item['page_number']}")
 
            if file_extension == ".pdf":
 
                logging.info("🚀Triggerd blob file is PDF.")
 
                # Create a temporary file
                temp_path = ""
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp:
                    temp.write(data_as_file.read())
                    temp_path = temp.name
 
                doc = pymupdf.open(temp_path)
                # ページ数をログに出力
                logging.info(f"🚀PDF Page count : {doc.page_count}")
 
                # ページごとにCosmosDBのアイテムを作成し、ページ画像がある場合はページの画像ファイルをBlobにを作成
                for page in doc:  # iterate through the pages
                    logging.info(f"🚀Page Number: {page.number}")
                    pix = page.get_pixmap()  # render page to an image
                    # Convert the pixmap to a PIL Image
                    img = Image.frombytes(
                        "RGB", [pix.width, pix.height], pix.samples)
 
                    binary_data = BytesIO()
                    img.save(binary_data, format='PNG')
                    binary_data.seek(0)
                    base64_data = base64.b64encode(
                        binary_data.getvalue()).decode()
 
                    # OpenAIに推論させるためのメッセージを作成
                    image_content = []
                    image_content.append({
                        "type": "image_url",
                        "image_url":
                        {
                            "url": f"data:image/jpeg;base64,{base64_data}"
                        },
                    })
                    messages = []
                    messages.append(
                        {"role": "system", "content": STR_AI_SYSTEMMESSAGE})
                    messages.append(
                        {"role": "user", "content": STR_SAMPLE_USERMESSAGE})
                    messages.append(
                        {"role": "user", "content": STR_SAMPLE_AIRESPONSE})
                    messages.append(
                        {"role": "user", "content": STR_AI_USERMESSAGE})
                    messages.append({"role": "user", "content": image_content})
 
                    # GPT4oにはjsonフォーマット指定がないので使えない。
                    response = azure_openai_service.getChatCompletionJsonStructuredMode(
                        messages, 0, 0, DocumentStructure)
 
                    doc_structured = response.choices[0].message.parsed
                    logging.info(f"🚀Response Format: {doc_structured}")
 
                    # contentをベクトル値に変換
                    content_vector = azure_openai_service.getEmbedding(
                        doc_structured.content)
 
                    # is_contain_imageがTrueの場合は、StorageAccountのBlobの"rag-images"に画像をアップロード
                    if doc_structured.is_contain_image:
                        # 格納するパスを生成。TriggerされたBlobのパスのフォルダとファイル名を、格納先フォルダにする。
                        parsed_url = urlparse(blob_url)
                        path_parts = parsed_url.path.split('/')
                        index = path_parts.index('rag-docs')
 
                        stored_image_path = file_name + \
                            "_page" + str(page.number) + ".png"
 
                        blob_client = blob_service_client.get_blob_client(
                            container=BLOB_CONTAINER_NAME_IMAGE, blob=stored_image_path)
                        blob_client.upload_blob(
                            base64.b64decode(base64_data), overwrite=True)
                        logging.info(
                            f"🚀Uploaded Image to Blob: {stored_image_path}")
 
                    # CosmosDBに登録するアイテムのオブジェクト
                    cosmos_page_obj = CosmosPageObj(file_name=file_name,
                                                    file_path=blob_url,
                                                    page_number=page.number,
                                                    content=doc_structured.content,
                                                    content_vector=content_vector,
                                                    keywords=doc_structured.keywords,
                                                    delete_flag=False,
                                                    is_contain_image=doc_structured.is_contain_image,
                                                    image_blob_path=stored_image_path if doc_structured.is_contain_image else None)
 
                    cosmos_service.insert_data(cosmos_page_obj.to_dict())
 
            else:
                # 対応していない拡張子なので、ログにWarningで出力
                logging.warning(
                    f"🚀❌Unsupported File Extension: \"{file_extension}\", File Name: \"{data_as_file.name}\"")
 
        elif event_dict.get("event_type") == "Microsoft.Storage.BlobDeleted":
            # Blobが削除された場合の処理
            logging.info(f"🚀Event Type: {event_dict.get('event_type')}")
 
            # blob_urlをCosmosのfile_pathで検索し、CosmosDBのアイテムを取得
            query = f"SELECT * FROM c WHERE c.file_path = \"{blob_url}\""
            items = cosmos_service.get_data(query)
 
            for item in items:
                # CosmosDBのアイテムを削除
                cosmos_service.delete_data(item["id"])
                logging.info(f"🚀Deleted data from CosmosDB: {item}")
 
                # PNGファイルをBlobに格納している場合は、BlobのImageを削除
                if item["is_contain_image"]:
                    blob_client = blob_service_client.get_blob_client(
                        container=BLOB_CONTAINER_NAME_IMAGE, blob=item["image_blob_path"])
                    blob_client.delete_blob()
                    logging.info(
                        f"🚀Deleted Image from Blob: {item['image_blob_path']}")
 
        else:
            # その他のイベントの場合
            logging.info(f"🚀Event Type: {event_dict.get('event_type')}")
 
    except Exception as e:
        logging.error(f"🚀❌Error at BlobTriggerEventGrid: {e}")
        raise e
 