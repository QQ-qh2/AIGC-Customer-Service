from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
import docx
import fitz 
try:
    from PIL import Image
    import pytesseract
    # 设置Tesseract路径 - 根据你的安装路径调整
    pytesseract.pytesseract.tesseract_cmd = r'D:\Tesseract\tesseract.exe'
except ImportError:
    Image = None
    pytesseract = None

app = Flask(__name__)
CORS(app)

# 加载.env文件
load_dotenv()
API_KEY = os.getenv("API_KEY", "")
API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

# 简单读取知识库

def load_knowledge():
    knowledge = ""
    # Second, walk through '测试资料' directory
    test_data_dir = "测试资料"
    tesseract_not_found_error_printed = False
    if os.path.exists(test_data_dir):
        for dirpath, _, filenames in os.walk(test_data_dir):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                try:
                    if filename.lower().endswith(".docx"):
                        doc = docx.Document(file_path)
                        full_text = [para.text for para in doc.paragraphs]
                        knowledge += "\n".join(full_text) + "\n"
                    elif filename.lower().endswith(".pdf"):
                        with fitz.open(file_path) as doc:
                            text = ""
                            for page_num in range(len(doc)):
                                page = doc.load_page(page_num)
                                text += page.get_text()  # type: ignore
                            knowledge += text + "\n"
                    elif filename.lower().endswith((".md", ".txt")):
                        with open(file_path, "r", encoding="utf-8") as f:
                            knowledge += f.read() + "\n"
                    elif Image and pytesseract and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                        try:
                            text = pytesseract.image_to_string(Image.open(file_path), lang='chi_sim+eng')
                            if text.strip():
                                knowledge += f"\n--- 来自图片 {filename} 的内容 ---\n{text.strip()}\n--- 图片内容结束 ---\n"
                        except pytesseract.TesseractNotFoundError:
                            if not tesseract_not_found_error_printed:
                                print("\n[重要提示] Tesseract OCR 未安装或未在系统 PATH 中。图片中的文字将无法被读取。")
                                print("请访问 https://github.com/tesseract-ocr/tesseract#installing-tesseract 下载并安装，然后将 tesseract.exe 所在目录添加到系统环境变量中。")
                                print("您可能还需要下载并安装 'chi_sim' (简体中文) 和 'eng' (英文) 语言包。\n")
                                tesseract_not_found_error_printed = True
                        except Exception as ocr_error:
                            print(f"OCR处理图片失败 {file_path}: {ocr_error}")
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue
    return knowledge


knowledge_base = load_knowledge()

def correct_question(question):
    """
    使用LLM纠正用户输入中的错别字
    """
    system_prompt = f"""
你是一个错别字纠正小助手。请修正以下句子中的错别字或语法错误，并直接返回修正后的句子，不要添加任何额外的解释或说明。

原始句子: {question}
修正后的句子:
"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen-turbo",
        "input": {
            "prompt": system_prompt
        }
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=data, timeout=5)
        if resp.status_code == 200:
            resp_json = resp.json()
            corrected_text = resp_json.get("output", {}).get("text", question).strip()
            # 有时模型会画蛇添足，我们要尽量取最核心的部分
            if "修正后的句子:" in corrected_text:
                corrected_text = corrected_text.split("修正后的句子:")[-1].strip()
            return corrected_text
        else:
            return question # 纠错失败，返回原问题
    except Exception:
        return question # 异常，返回原问题


def call_aliyun_bailian(question, knowledge_base=""):
    # --- 优化后的Prompt ---
    system_prompt = f"""
你是一个名叫"小丽"的专业、耐心且友好的AIGC智能客服。你的任务是根据提供的'知识库'内容，准确地回答'用户问题'。

请严格遵循以下规则：
1.  **身份角色**: 你是客服代表"小丽"，不是一个AI模型。请不要在回答中提及"大语言模型"、"AI"等词语。
2.  **沟通风格**: 语气要亲切、专业，使用简洁明了的语言。始终保持礼貌，风格应友好、耐心、专业。
3.  **核心任务**: 严格基于'知识库'内容进行回答。如果知识库没有相关信息，请诚恳地回答："非常抱歉，关于这个问题我暂时没有查询到相关信息，您可以咨询我们的人工客服获取更详细的帮助。"
4.  **禁止行为**: 严禁编造任何'知识库'中不存在的信息。
5.  **价值观**: 始终以用户需求为中心，提供优质服务。 不断优化服务流程，提高服务质量。 确保提供的信息真实可靠，不误导用户。
6.  **主要目标**: 提供准确、及时的信息查询服务。 解答用户疑问，提升用户满意度。 优化用户体验，增强用户对服务的信任感。 

---
[知识库开始]
{knowledge_base}
[知识库结束]
---
"""
    
    final_prompt = f"{system_prompt}\n用户问题: {question}"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen-turbo",  # 如有需要可更换为你实际的模型名
        "input": {
            "prompt": final_prompt
        }
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=data, timeout=20)
        if resp.status_code == 200:
            resp_json = resp.json()
            # 兼容不同返回结构
            if "output" in resp_json and "text" in resp_json["output"]:
                return resp_json["output"]["text"]
            elif "result" in resp_json:
                return resp_json["result"]
            else:
                return "很抱歉，未能找到相关答案。"
        else:
            return "调用大模型失败，请稍后再试。"
    except Exception as e:
        return "调用大模型异常，请检查网络或API配置。"

@app.route("/ask", methods=["POST"])
def ask():
    if not request.json:
        return jsonify({"answer": "无效的请求，请发送JSON格式的数据。"}), 400
    user_question = request.json.get("question", "")
    if not user_question:
        return jsonify({"answer": "请输入您的问题。"}), 400
    
    # 1. 纠正问题中的错别字
    corrected_question = correct_question(user_question)
        
    # 2. 使用纠正后的问题进行问答
    answer = call_aliyun_bailian(corrected_question, knowledge_base)
    return jsonify({"answer": answer})

if __name__ == "__main__":
    app.run(debug=True)