import os
from lxml import etree as ET
from xml.sax.saxutils import unescape, escape
import re
from tqdm import tqdm # Импортируем tqdm

# --- Конфигурация ---
INPUT_XML_FILE_TO_CLEAN = "translation_output_final/translated_with_inline_originals.xml" 
OUTPUT_XML_FILE_CLEANED = "translation_output_final/translated_cleaned_lxml_tqdm.xml"
TEXT_SEPARATOR = "\n---\n"

# Обновленная функция post_process_translation
def post_process_translation(text):
    if not text:
        return ""
    
    # original_text_for_debug = text

    # --- Обработка точек ---
    text = re.sub(r'\.{3,}', '___ELLIPSIS___', text) # Сохраняем многоточия

    # 1. Убираем лишние точки и пробелы вокруг них, оставляя одну точку и один пробел после, если далее слово
    # "word . . . word2" -> "word. word2"
    # "word ... word2" (многоточие) -> "word ... word2" (не трогаем)
    # " . . . word" -> ". word"
    
    # Сначала разбираемся с последовательностями "пробел-точка"
    # " . ." -> ". " (оставляем один пробел после точки)
    text = re.sub(r'(\s*\.\s*){2,}', '. ', text) 
    
    # "слово ." -> "слово."
    text = re.sub(r'(?<=\w)\s+\.$', '.', text)
    # "слово . слово" -> "слово. слово"
    text = re.sub(r'(?<=\w)\s+\.(?=\s+\w)', '. ', text)
    # " .слово" (в начале или после пробела) -> ". слово"
    text = re.sub(r'^\s*\.(?=\s*\w)', '. ', text) # Для начала строки
    text = re.sub(r'(?<=\s)\s*\.(?=\s*\w)', '. ', text) # Для после пробела

    # Итеративная очистка " . " в конце, если предыдущие шаги не справились полностью
    idx = 0
    max_iters = 5 # Уменьшил, т.к. предыдущие шаги должны были многое сделать
    while idx < max_iters and (text.endswith(" .") or text.endswith(" . ")):
        if text.endswith(" . "):
            text = text[:-3].strip()
        elif text.endswith(" ."):
            text = text[:-2].strip()
        idx += 1
        
    if text and text[-1].isalnum() and not text.endswith('.') and not text.endswith('___ELLIPSIS___'):
        text += '.'
    
    text = text.replace('___ELLIPSIS___', '...')

    # --- Обработка дефисов/тире ---
    text = re.sub(r'(?<=\w)\s+-\s+(?=\w)', '-', text)
    text = re.sub(r'\s+-\s*$', '', text) 
    text = re.sub(r'^\s*-\s+', '', text) 
    text = re.sub(r'(?<=\w)\s+-\s+\.(?=\s|$)', '.', text)

    # --- Обработка восклицательных знаков ---
    text = re.sub(r'!{2,}', '!', text) 
    text = re.sub(r'\s*!\s*!\s*', '! ', text) 

    # --- Обработка вопросительных знаков ---
    text = re.sub(r'\?{2,}', '?', text) 
    text = re.sub(r'\s*\?\s*\?\s*', '? ', text) 

    # --- Общие правила очистки ---
    text = re.sub(r'\s+([.,;:!?])', r'\1', text)
    text = re.sub(r'\s{2,}', ' ', text)
    text = text.strip()
        
    # if text != original_text_for_debug:
    #     print(f"DEBUG Post-Process: \n  Original: '{original_text_for_debug}'\n  Cleaned:  '{text}'")
        
    return text
# --- Основная логика ---
def main():
    print(f"Starting to process file: {INPUT_XML_FILE_TO_CLEAN}")
    try:
        parser = ET.XMLParser(remove_blank_text=True)
        print("Parsing XML file...") 
        tree = ET.parse(INPUT_XML_FILE_TO_CLEAN, parser)
        root = tree.getroot()
        print("XML file parsed.")
    except FileNotFoundError:
        print(f"Error: Input file not found at {INPUT_XML_FILE_TO_CLEAN}")
        return
    except ET.XMLSyntaxError as e: 
        print(f"Error: Could not parse XML file {INPUT_XML_FILE_TO_CLEAN}: {e}")
        return

    nodes_to_process = []
    # Сначала соберем все узлы, которые нужно обработать, чтобы tqdm знал общее количество
    print("Collecting text nodes for processing...")
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.lower() in ["infotexts", "style"]:
            continue
        if not isinstance(element.tag, str): 
             continue
        if not element.text: # Пропускаем теги без текстового содержимого
            continue
        nodes_to_process.append(element)
    
    if not nodes_to_process:
        print("No text nodes found to process.")
        return

    print(f"Found {len(nodes_to_process)} text nodes. Starting cleaning process...")
    
    nodes_changed = 0

    # Оборачиваем итерацию по узлам в tqdm для отображения прогресс-бара
    # desc="Cleaning XML" - это описание для прогресс-бара
    # unit="node" - это единица измерения (обрабатываем "узел")
    for element in tqdm(nodes_to_process, desc="Cleaning XML", unit="node", ncols=100): # ncols для ширины бара
        escaped_full_text = element.text # element.text здесь уже должен существовать
        unescaped_full_text = unescape(escaped_full_text)
        
        parts = unescaped_full_text.split(TEXT_SEPARATOR, 1)
        
        new_unescaped_full_text = unescaped_full_text 
        changed_this_node = False

        if len(parts) == 2:
            translated_part = parts[0]
            original_part = parts[1]
            cleaned_translated_part = post_process_translation(translated_part)
            
            if cleaned_translated_part != translated_part:
                changed_this_node = True
            new_unescaped_full_text = f"{cleaned_translated_part}{TEXT_SEPARATOR}{original_part}"
        else:
            cleaned_full_text = post_process_translation(unescaped_full_text)
            if cleaned_full_text != unescaped_full_text:
                changed_this_node = True
            new_unescaped_full_text = cleaned_full_text
        
        if changed_this_node:
            nodes_changed += 1
        
        element.text = escape(new_unescaped_full_text)

    print(f"\nCleaning finished. Processed {len(nodes_to_process)} text elements.") # \n чтобы не затереть бар
    print(f"Changed {nodes_changed} text elements due to cleaning.")

    print("Saving cleaned XML file...")
    try:
        output_dir = os.path.dirname(OUTPUT_XML_FILE_CLEANED)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        tree.write(OUTPUT_XML_FILE_CLEANED, encoding="utf-8", xml_declaration=True, pretty_print=True)
        print(f"Cleaned XML saved to: {os.path.abspath(OUTPUT_XML_FILE_CLEANED)}")
    except Exception as e:
        print(f"Error saving cleaned XML file: {e}")

if __name__ == "__main__":
    main()