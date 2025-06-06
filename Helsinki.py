import os
import xml.etree.ElementTree as ET
from transformers import MarianMTModel, MarianTokenizer
import torch
from xml.sax.saxutils import unescape, escape # Для работы с экранированным текстом
import time # Для индикатора прогресса

# --- Конфигурация ---
INPUT_XML_FILE = "translation_output_for_extractor/strings_for_translation.xml"
OUTPUT_XML_FILE_TRANSLATED = "translation_output_final/translated_with_inline_originals.xml" # Изменил имя файла

MODEL_NAME = 'Helsinki-NLP/opus-mt-en-ru'
TARGET_LANGUAGE_CODE_ATTR = "Russian"
TARGET_TRANSLATED_NAME_ATTR = "Русский"

ATTEMPT_MODEL_TRANSLATION = True # True для перевода, False для "Русский (Оригинал)"

# Разделитель между переводом и оригиналом в тексте элемента
# \n для новой строки. Вы можете использовать что-то вроде " --- Original: " если хотите.
TEXT_SEPARATOR = "\n---\n" # \n добавит перенос строки до и после

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {DEVICE}")

# --- Функции для модели (load_model_and_tokenizer без изменений) ---
def load_model_and_tokenizer(model_name):
    print(f"Loading tokenizer for {model_name}...")
    try:
        tokenizer = MarianTokenizer.from_pretrained(model_name)
        print(f"Loading model {model_name}...")
        model = MarianMTModel.from_pretrained(model_name)
        model.to(DEVICE)
        model.eval()
        print("Model and tokenizer loaded.")
        return model, tokenizer
    except Exception as e:
        print(f"Error loading model/tokenizer: {e}")
        print("Ensure you have an internet connection for the first download, or the model is cached.")
        print("Try: pip install sentencepiece sacremoses")
        return None, None

def translate_texts_batch(texts_to_translate, model, tokenizer, batch_size=8):
    if not model or not tokenizer:
        print("Model or tokenizer not loaded, skipping translation.")
        return [f"[MODEL_NOT_LOADED] {text}" for text in texts_to_translate]

    translations = []
    total_texts = len(texts_to_translate)
    print(f"Starting translation for {total_texts} texts with batch_size={batch_size}...")
    start_time_total = time.time()

    for i in range(0, total_texts, batch_size):
        batch_original_texts = texts_to_translate[i:i+batch_size]
        
        if not any(t.strip() for t in batch_original_texts):
            translations.extend([""] * len(batch_original_texts))
            if i + batch_size >= total_texts: # Прогресс для последнего батча, если он пустой
                elapsed_total = time.time() - start_time_total
                print(f"  Progress: {total_texts}/{total_texts} (100.00%) | Total time: {elapsed_total:.2f}s")
            continue

        try:
            start_time_batch = time.time()
            tokenized_batch = tokenizer(batch_original_texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(DEVICE)
            with torch.no_grad():
                translated_tokens = model.generate(**tokenized_batch)
            batch_translations = tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)
            translations.extend(batch_translations)
            
            # Индикатор прогресса
            processed_count = min(i + batch_size, total_texts)
            percentage = (processed_count / total_texts) * 100
            elapsed_batch = time.time() - start_time_batch
            elapsed_total = time.time() - start_time_total
            
            # Печатаем прогресс каждые N батчей или в конце
            # (i // batch_size) + 1 -- это номер текущего батча (начиная с 1)
            if (i // batch_size + 1) % 1 == 0 or processed_count == total_texts: # Печатать для каждого батча
                print(f"  Progress: {processed_count}/{total_texts} ({percentage:.2f}%) | Batch time: {elapsed_batch:.2f}s | Total time: {elapsed_total:.2f}s")

        except Exception as e:
            print(f"Error translating batch starting with '{batch_original_texts[0][:30]}...': {e}")
            translations.extend([f"[TRANSLATION_ERROR] {text}" for text in batch_original_texts])
            # Обновляем прогресс даже при ошибке
            processed_count = min(i + batch_size, total_texts)
            percentage = (processed_count / total_texts) * 100
            elapsed_total = time.time() - start_time_total
            print(f"  Progress: {processed_count}/{total_texts} ({percentage:.2f}%) | ERROR IN BATCH | Total time: {elapsed_total:.2f}s")

    print(f"Translation finished for {total_texts} texts. Total time: {time.time() - start_time_total:.2f}s")
    return translations

# --- Основная логика ---
def main():
    model, tokenizer = None, None
    if ATTEMPT_MODEL_TRANSLATION:
        model, tokenizer = load_model_and_tokenizer(MODEL_NAME)
        if not model or not tokenizer:
            print("Failed to load model. Translation will be skipped, structure will be 'Original Text [SEPARATOR] Original Text'.")

    try:
        tree = ET.parse(INPUT_XML_FILE)
        root = tree.getroot()
    except FileNotFoundError:
        print(f"Error: Input file not found at {INPUT_XML_FILE}")
        return
    except ET.ParseError as e:
        print(f"Error: Could not parse XML file {INPUT_XML_FILE}: {e}")
        return
    
    # Списки для текстов
    original_texts_unescaped = [] # Расэкранированные оригиналы
    elements_to_update = []       # XML элементы для обновления

    print("Extracting texts from input XML...")
    for element in root.iter():
        is_comment_node = isinstance(element.tag, type(ET.Comment))
        if is_comment_node or element.tag.lower() in ["infotexts", "style"] or not element.text:
            continue

        escaped_text_from_input_xml = element.text.strip()
        if escaped_text_from_input_xml:
            unescaped_original = unescape(escaped_text_from_input_xml)
            original_texts_unescaped.append(unescaped_original)
            elements_to_update.append(element)

    if not original_texts_unescaped:
        print("No text entries found to process in the XML.")
        return
    print(f"Found {len(original_texts_unescaped)} text entries to process.")

    # Перевод (или использование оригинала если перевод выключен/не удался)
    translated_or_marked_texts = []
    if ATTEMPT_MODEL_TRANSLATION and model and tokenizer:
        translated_results = translate_texts_batch(original_texts_unescaped, model, tokenizer, batch_size=8) # Меньше батч для CPU, больше для GPU
        if len(translated_results) == len(original_texts_unescaped):
            translated_or_marked_texts = translated_results
        else:
            print("Error: Mismatch in count of translated texts. Using originals as fallback for structure.")
            translated_or_marked_texts = original_texts_unescaped
    else:
        if ATTEMPT_MODEL_TRANSLATION and (not model or not tokenizer):
            print("Model translation was requested but model/tokenizer failed to load. Using original texts for structure.")
        else:
            print("Model translation is disabled. Using original texts for structure.")
        translated_or_marked_texts = original_texts_unescaped

    # Обновляем XML-дерево
    print("Updating XML tree with combined translated/original text...")
    if len(translated_or_marked_texts) == len(elements_to_update) == len(original_texts_unescaped):
        for i, element_node in enumerate(elements_to_update):
            original_text = original_texts_unescaped[i]
            processed_text = translated_or_marked_texts[i] # Это либо перевод, либо оригинал

            # Формируем комбинированный текст
            # Если перевод не удался (содержит маркер ошибки) или если перевод = оригиналу,
            # можно сделать по-другому, но пока просто комбинируем.
            combined_text = f"{processed_text}{TEXT_SEPARATOR}{original_text}"
            
            # Экранируем финальный комбинированный текст для вставки в XML
            escaped_combined_text = escape(combined_text)
            
            element_node.text = escaped_combined_text
            # Очищаем старые дочерние узлы (например, комментарии из предыдущих запусков)
            for child in list(element_node):
                 element_node.remove(child)
    else:
        print("Error: Mismatch in array lengths during XML update. Aborting XML update.")
        return

    # Обновляем атрибуты корневого элемента
    root.set('language', TARGET_LANGUAGE_CODE_ATTR)
    root.set('translatedname', TARGET_TRANSLATED_NAME_ATTR)
    if 'nowhitespace' not in root.attrib:
        root.set('nowhitespace', "false")

    # Сохраняем
    try:
        os.makedirs(os.path.dirname(OUTPUT_XML_FILE_TRANSLATED), exist_ok=True)
        # Для "красивой" печати на Python 3.9+
        if hasattr(ET, 'indent'):
            ET.indent(tree)
        tree.write(OUTPUT_XML_FILE_TRANSLATED, encoding="utf-8", xml_declaration=True)
        print(f"Processed XML with inline originals saved to: {os.path.abspath(OUTPUT_XML_FILE_TRANSLATED)}")
    except Exception as e:
        print(f"Error saving XML file: {e}")
        if "ET.indent" in str(e) and not hasattr(ET, 'indent'):
             print("Note: ET.indent(tree) for pretty printing is available in Python 3.9+. Try commenting it out if you use an older version.")

if __name__ == "__main__":
    main()