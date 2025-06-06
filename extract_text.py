import os
import xml.etree.ElementTree as ET
import re
from xml.sax.saxutils import escape # Для экранирования текстового содержимого XML
from collections import defaultdict # Для удобного подсчета

# --- Конфигурация ---
# Язык, который мы хотим извлечь (исходный язык текстов из XML)
SOURCE_LANGUAGE_FILTER = "English"
# Язык, наличие которого в XML означает, что строка уже переведена и ее не нужно включать
EXISTING_TRANSLATION_LANGUAGE = "Russian"

# Язык, который будет указан в выходном XML-файле (целевой язык перевода)
TARGET_OUTPUT_LANGUAGE = "Russian" # Для атрибута language в итоговом файле
TARGET_OUTPUT_TRANSLATED_NAME = "Русский" # Для атрибута translatedname в итоговом файле

# --- НОВЫЙ ПАРАМЕТР: Порог для вывода часто встречающихся тегов ---
# Выводить теги, встретившиеся это количество раз или больше в рамках одного мода.
# Можно также сделать глобальный подсчет, если убрать mod_name из ключей статистики.
DUPLICATE_TAG_THRESHOLD = 5

# --- Вспомогательные функции ---

def sanitize_xml_tag_name(name):
    """Санитизирует строку, чтобы она была валидным именем XML-тега."""
    if not isinstance(name, str):
        name = str(name)
    
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^a-zA-Z0-9_.-]', '', name)
    
    if not name:
        return "sanitized_empty_tag"
        
    if re.match(r'^[0-9.-]', name) or name.lower().startswith("xml"):
        name = "_" + name
    
    if not name:
        return "invalid_tag_fallback"
    return name

def get_mod_name_from_path(filepath, base_mods_directory):
    """Определяет имя мода на основе пути к файлу и корневой директории модов."""
    try:
        normalized_filepath = os.path.normpath(filepath)
        normalized_base_mods_directory = os.path.normpath(base_mods_directory)
        
        # Проверяем, является ли base_mods_directory предком filepath
        if not normalized_filepath.startswith(normalized_base_mods_directory):
            # Если нет, пытаемся взять имя родительской папки файла
            parent_dir = os.path.basename(os.path.dirname(normalized_filepath))
            return parent_dir if parent_dir else "UnknownModContext"

        relative_path = os.path.relpath(normalized_filepath, normalized_base_mods_directory)
        path_parts = relative_path.split(os.sep)
        
        if path_parts and path_parts[0] not in ('.', '..') and path_parts[0] != '':
            return path_parts[0]
        else:
            # Если файл в корне base_mods_directory или base_mods_directory="."
            if base_mods_directory == ".": # или os.path.abspath(base_mods_directory) == os.path.abspath(os.path.dirname(normalized_filepath))
                path_segments = normalized_filepath.split(os.sep)
                # Если путь вида "ModName/subfolder/file.xml" при base_mods_directory="."
                if len(path_segments) > 1 and path_segments[0] not in ('.', '..'):
                    return path_segments[0]
                # Если файл вида "./file.xml" или в папке, которую не опознать как мод
                # Можно вернуть имя ближайшей родительской папки файла
                parent_dir_name = os.path.basename(os.path.dirname(normalized_filepath))
                return parent_dir_name if parent_dir_name and parent_dir_name != "." else "RootOrUncategorized"
            # Если base_mods_directory это имя самой папки модов, например "Mods"
            # и файл лежит прямо в ней (не в подпапке мода), то это маловероятно для структуры модов.
            # Скорее всего, это файл конфигурации самого скрипта или что-то подобное.
            return os.path.basename(normalized_base_mods_directory) 

    except ValueError: # Может возникнуть, если пути на разных дисках и т.п.
        parent_dir = os.path.basename(os.path.dirname(normalized_filepath))
        return parent_dir if parent_dir else "UnknownModPathError"


def extract_keys_from_xml(filepath, lang_to_extract):
    """Извлекает ключи (санитизированные full_tag) из XML файла для указанного языка."""
    keys = set()
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        file_language = root.get("language")

        if file_language and file_language.lower() == lang_to_extract.lower():
            for element in root.iter():
                if element.tag.lower() in ["infotexts", "style"]:
                    continue
                
                original_tag_name = element.tag
                id_val = element.get('identifier') or element.get('name')
                
                sanitized_main_tag = sanitize_xml_tag_name(original_tag_name)
                if id_val:
                    sanitized_id_val = sanitize_xml_tag_name(id_val)
                    if sanitized_id_val and sanitized_id_val not in ("sanitized_empty_tag", "invalid_tag_fallback"):
                        full_tag = f"{sanitized_main_tag}.{sanitized_id_val}"
                    else:
                        full_tag = sanitized_main_tag
                else:
                    full_tag = sanitized_main_tag
                
                full_tag = sanitize_xml_tag_name(full_tag) 
                keys.add(full_tag)
        return keys
    except ET.ParseError:
        return set()
    except Exception:
        return set()


def extract_text_from_xml_file(filepath, base_mods_directory, lang_filter):
    """Извлекает (tag, text, path, mod) из XML, если он соответствует языковому фильтру."""
    text_list_for_file = []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        file_language = root.get("language")

        process_this_file = False
        if file_language:
            if file_language.lower() == lang_filter.lower():
                process_this_file = True
        elif lang_filter.lower() == "english": 
            process_this_file = True
        
        if not process_this_file:
            return []

        mod_name = get_mod_name_from_path(filepath, base_mods_directory)

        # ОБНОВЛЕННЫЙ И РАСШИРЕННЫЙ СПИСОК ИСКЛЮЧЕНИЙ (ориентируйтесь на реальные теги из вашей игры)
        # Список тегов, которые обычно не содержат переводимый текст
        # или являются контейнерами/служебными тегами
        excluded_tags = {
            "infotexts", "style", "sound", "sprite", "animation", "limb", "trigger",
            "statvalue", "objective", "particleemitter", "damagemodifier", "attack",
            "character", "job", "item", "structure", "locationtype",
            "levelgenerationparameters", "mission", "event", "eventset", "characterinfo",
            "ragdoll", "campaignsettings", "destructible", "fabricator", "deconstructor",
            "repairable", "controller", "connectionpanel", "engine", "pump", "reactor",
            "turret", "itemcontainer", "door", "medicalclinic", "talenttree", "talents",
            "submarine", "shuttle", "upgradecategory", "upgrademodule", "afflictions",
            "geneticmaterial", "mapgenerationparameters", "allowwhenriding", "allowatsub",
            "allowatbeaconstation", "allowatoutpost", "allowatcity", "allowatcolonies",
            "allowatdestroyeddoutpost", "allowatabandonedoutpost", "allowatruins",
            "allowatwreck", "allowatcave", "allowatpirateoutpost", "commonness",
            "requiredcampaignlevel", "campaignonly", "health", "price", "fabricationtime", 
            "deconstructtime", "containable", "spritecolor", "decorativesprite", "music",
            # Дополнительные общие исключения:
            "useverb", "examineverb", "pickupverb", # Часто стандартные и не меняются
            "requireditem", "requiredskill", "itemidentifier", "structureidentifier",
            "characteridentifier", "soundfile", "musicfile", "imagefile", "texture", "animationfile",
            "soundchannel", "soundvolume", "soundrange", "loop", "playonstart",
            "color", "vector2", "vector3", "vector4", "rect", "point", "offset", "scale", "size",
            "limbname", "bonename", "jointname", # Часто внутренние идентификаторы
            "state", "type", "category", "group", "layer", "order", "slot",
            "targettag", "sourcetag", "linkedsub", "linkeduuid",
            "variable", "property", "value", # Если их значения не являются текстом (числа, bool)
            "button", # Если это имя кнопки для скриптинга, а не видимый текст
            "command", "script", "function", "eventname",
            "dialogflag", "objectiveflag", "questflag", # Флаги, а не текст
            "classname", "speciesname", # Часто внутренние ID
            "filename", "path", # Пути к файлам
            "default", # Если это значение по умолчанию, которое не должно меняться
            "ambientmccormicks", 'returns', 'remarks', 'c', 'para', 'see', 'param.il', 'param.steamid', 'param.appid', 'param.name', 'code', 'param.filename', 'param.type', 'param.character', 'param.frequency', 'param.sampleRate', 'param.action', 'param.identifier', 'param.interactableFor', 'param.statName', 'param.value', 'param.position', 'param.assembly', 'param.createNetworkEvent', 'param.defult', 'param.force', 'param.load', 'param.predicate', 'param.prefab', 'param.radius', 'typeparam.T', 'exception', 'override', 'locationchange.base.changeto.military', 'eventtext.blockadealarm.breakin', 'locationnameformat.mine', 'loadingscreentip', 'dialogturnoffsonar', 'dialogcantfindanechoicsuit', 'lua_name', 'lua_description', "author", "id", "lua_name", "param.load", "param.force", 'summary', 'returns', 'remarks', 'c', 'para', 'see', 'param.il', 'param.steamid', 'param.appid', 'param.name', 'code', 'param.filename', 'param.type', 'param.character', 'param.frequency', 'param.sampleRate', 'param.action', 'param.identifier', 'param.interactableFor', 'param.statName', 'param.value', 'param.position', 'param.assembly', 'param.createNetworkEvent', 'param.defult', 'param.force', 'param.load', 'param.predicate', 'param.prefab', 'param.radius', 'typeparam.T', 'exception', 'override', 'locationchange.base.changeto.military', 'eventtext.blockadealarm.breakin', 'locationnameformat.mine', 'loadingscreentip', 'dialogturnoffsonar', 'dialogcantfindanechoicsuit', 'lua_name', 'lua_description', "param.createNetworkEvent", 

    # ваш пример
        }

        for element in root.iter():
            if element.tag.lower() in excluded_tags:
                continue

            if element.text: 
                original_tag_name = element.tag
                id_val = element.get('identifier') or element.get('name')
                
                sanitized_main_tag = sanitize_xml_tag_name(original_tag_name)
                if id_val:
                    sanitized_id_val = sanitize_xml_tag_name(id_val)
                    if sanitized_id_val and sanitized_id_val not in ("sanitized_empty_tag", "invalid_tag_fallback"):
                        full_tag = f"{sanitized_main_tag}.{sanitized_id_val}"
                    else:
                        full_tag = sanitized_main_tag
                else:
                    full_tag = sanitized_main_tag
                
                full_tag = sanitize_xml_tag_name(full_tag) 

                stripped_text = element.text.strip()
                if stripped_text: 
                    escaped_text_content = escape(stripped_text)
                    text_list_for_file.append((full_tag, escaped_text_content, filepath, mod_name))
        return text_list_for_file
    except ET.ParseError:
        print(f"XML Parse Error processing file {filepath}. Skipping.")
        return []
    except Exception as e:
        print(f"Error processing XML file {filepath}: {e}")
        return []

def extract_text_from_lua_file(filepath, base_mods_directory):
    """Извлекает тексты из Lua файлов."""
    text_list_for_file = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        mod_name = get_mod_name_from_path(filepath, base_mods_directory)
        
        kv_pairs = re.findall(r'(?i)\b(name|label|displayname|tooltip|description|text)\s*=\s*"([^"]*)"', content)
        for key, value in kv_pairs:
            clean_value = value.strip()
            if clean_value:
                lua_tag = sanitize_xml_tag_name(f"lua_{key.lower()}")
                escaped_value = escape(clean_value)
                text_list_for_file.append((lua_tag, escaped_value, filepath, mod_name))

        text_func_calls = re.findall(r'(?i)\b(?:Text|Texts\.Get|Game\.ShowMessageBox)\s*\(\s*"([^"]*)"', content)
        for text_val in text_func_calls:
            clean_value = text_val.strip()
            if clean_value:
                lua_tag = sanitize_xml_tag_name("lua_func_text") # более общий тег
                escaped_value = escape(clean_value)
                text_list_for_file.append((lua_tag, escaped_value, filepath, mod_name))
        
        return text_list_for_file
    except Exception as e:
        print(f"Error processing Lua file {filepath}: {e}")
        return []

# --- Основная логика ---

def collect_and_filter_texts(mods_root_directory):
    """Собирает все тексты, фильтрует по языку, исключает переведенные, дедуплицирует."""
    
    translated_xml_keys_by_mod = {} 
    print(f"Phase 1: Scanning for existing XML translations in '{EXISTING_TRANSLATION_LANGUAGE}'...")
    xml_files_count_phase1 = 0
    for root_dir_scanned, _, files in os.walk(mods_root_directory):
        for file in files:
            if file.endswith(".xml"):
                xml_files_count_phase1 +=1
                filepath = os.path.join(root_dir_scanned, file)
                mod_name_for_keys = get_mod_name_from_path(filepath, mods_root_directory)
                
                keys_from_file = extract_keys_from_xml(filepath, EXISTING_TRANSLATION_LANGUAGE)
                if keys_from_file:
                    if mod_name_for_keys not in translated_xml_keys_by_mod:
                        translated_xml_keys_by_mod[mod_name_for_keys] = set()
                    translated_xml_keys_by_mod[mod_name_for_keys].update(keys_from_file)

    total_translated_keys = sum(len(s) for s in translated_xml_keys_by_mod.values())
    print(f"Scanned {xml_files_count_phase1} XML files. Found {total_translated_keys} XML tags in {len(translated_xml_keys_by_mod)} mods already translated to '{EXISTING_TRANSLATION_LANGUAGE}'.")

    all_source_texts_to_translate = []
    seen_global_text_keys_for_dedup = set()

    # --- НОВОЕ: Словари для сбора статистики по тегам ---
    # (mod_name, full_tag) -> count
    tag_occurrences = defaultdict(int)
    # (mod_name, full_tag) -> set of (escaped_text, original_filepath)
    tag_details_map = defaultdict(set)


    print(f"\nPhase 2: Scanning for source texts ('{SOURCE_LANGUAGE_FILTER}' XML & Lua), filtering and deduplicating...")
    processed_files_count_phase2 = 0
    
    for root_dir_scanned, _, files in os.walk(mods_root_directory):
        for file in files:
            filepath = os.path.join(root_dir_scanned, file)
            current_file_source_texts = []
            is_lua_file = False

            if file.endswith(".xml"):
                processed_files_count_phase2 += 1
                current_file_source_texts = extract_text_from_xml_file(filepath, mods_root_directory, SOURCE_LANGUAGE_FILTER)
            elif file.endswith(".lua"):
                processed_files_count_phase2 += 1
                is_lua_file = True
                current_file_source_texts = extract_text_from_lua_file(filepath, mods_root_directory)

            for full_tag, escaped_original_text, source_filepath, mod_name in current_file_source_texts:
                # --- НОВОЕ: Сбор статистики ---
                tag_key_for_stats = (mod_name, full_tag)
                tag_occurrences[tag_key_for_stats] += 1
                # Сохраняем экранированный текст и нормализованный путь к файлу
                tag_details_map[tag_key_for_stats].add((escaped_original_text, os.path.normpath(source_filepath)))

                is_already_translated_in_mod = False
                if not is_lua_file: 
                    if mod_name in translated_xml_keys_by_mod and \
                       full_tag in translated_xml_keys_by_mod[mod_name]:
                        is_already_translated_in_mod = True
                
                text_key_for_dedup = (mod_name, full_tag, escaped_original_text)
                
                if text_key_for_dedup not in seen_global_text_keys_for_dedup and not is_already_translated_in_mod:
                    seen_global_text_keys_for_dedup.add(text_key_for_dedup)
                    all_source_texts_to_translate.append((full_tag, escaped_original_text, source_filepath, mod_name))

    print(f"Processed {processed_files_count_phase2} XML/Lua files for source text.")
    
    all_source_texts_to_translate.sort(key=lambda x: (x[3].lower(), x[0].lower(), x[1].lower()))
    
    # --- НОВОЕ: Анализ и формирование информации о часто встречающихся тегах ---
    frequent_tags_report = []
    for (mod_name, tag_name), count in tag_occurrences.items():
        if count >= DUPLICATE_TAG_THRESHOLD:
            details = tag_details_map[(mod_name, tag_name)]
            unique_texts_in_tag = {text for text, path in details}
            unique_filepaths_in_tag = {path for text, path in details}
            
            frequent_tags_report.append({
                "mod_name": mod_name,
                "tag_name": tag_name,
                "count": count,
                "unique_texts": unique_texts_in_tag,
                "unique_filepaths": unique_filepaths_in_tag,
                "sample_details": list(details)[:min(3, len(details))] # Первые 3 примера (текст, путь)
            })
    
    frequent_tags_report.sort(key=lambda x: (x["mod_name"].lower(), -x["count"], x["tag_name"].lower()))

    return all_source_texts_to_translate, frequent_tags_report


def save_texts_to_final_xml(text_items_list, output_filepath, lang_attr, translated_name_attr):
    """Сохраняет собранные и отфильтрованные тексты в итоговый XML."""
    output_dir = os.path.dirname(output_filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(output_filepath, "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(f'<infotexts language="{lang_attr}" nowhitespace="false" translatedname="{translated_name_attr}">\n\n')
        
        current_mod_for_comment = None
        for full_tag, escaped_original_text_content, source_filepath, mod_name in text_items_list:
            if mod_name != current_mod_for_comment:
                if current_mod_for_comment is not None:
                    f.write('\n') 
                f.write(f'  <!-- Texts from Mod: {mod_name} -->\n')
                current_mod_for_comment = mod_name
            
            f.write(f'  <!-- Original File: {os.path.normpath(source_filepath)} -->\n')
            f.write(f'  <{full_tag}>{escaped_original_text_content}</{full_tag}>\n')
        
        f.write('\n</infotexts>\n')

# --- Точка входа ---
if __name__ == "__main__":
    mods_collection_directory = "." 
    
    output_directory_name = "translation_output_for_extractor"
    output_filename = "strings_for_translation.xml"
    full_output_path = os.path.join(output_directory_name, output_filename)

    print(f"--- Starting Text Extraction Script ---")
    print(f"Mods directory: {os.path.abspath(mods_collection_directory)}")
    print(f"Source language (XML): '{SOURCE_LANGUAGE_FILTER}'")
    print(f"Excluding XML texts if already translated to '{EXISTING_TRANSLATION_LANGUAGE}' (within the same mod).")
    print(f"Output will be prepared for target language '{TARGET_OUTPUT_LANGUAGE}'.")
    print(f"Threshold for reporting frequent tags: {DUPLICATE_TAG_THRESHOLD} occurrences per mod.")
    print(f"-----------------------------------------")
    
    final_texts_for_translation, frequent_tags_data = collect_and_filter_texts(mods_collection_directory)
    
    if final_texts_for_translation:
        print(f"\n--- Results: Texts for Translation ---")
        print(f"Found {len(final_texts_for_translation)} unique text entries requiring translation.")
        save_texts_to_final_xml(final_texts_for_translation, full_output_path, TARGET_OUTPUT_LANGUAGE, TARGET_OUTPUT_TRANSLATED_NAME)
        print(f"Output file saved to: {os.path.abspath(full_output_path)}")
    else:
        print(f"\n--- Results: Texts for Translation ---")
        print(f"No new texts found needing translation based on the specified criteria.")
    
    if frequent_tags_data:
        print(f"\n--- Frequent Tags Analysis (>= {DUPLICATE_TAG_THRESHOLD} occurrences per tag per mod) ---")
        print(f"Found {len(frequent_tags_data)} tag types that appear frequently. ")
        print(f"Review these tags. If their content is not meant for translation or is redundant,")
        print(f"consider adding the original XML tag name (before sanitization) to the 'excluded_tags' list ")
        print(f"in the 'extract_text_from_xml_file' function, or adjust Lua parsing if needed.")
        
        for tag_info in frequent_tags_data:
            print(f"\n  Mod: {tag_info['mod_name']}")
            print(f"    Tag (sanitized): '{tag_info['tag_name']}'")
            print(f"    Occurrences: {tag_info['count']}")
            
            unique_texts = list(tag_info['unique_texts'])
            if len(unique_texts) == 1:
                print(f"    Associated Text (consistent): \"{unique_texts[0]}\"")
            else:
                print(f"    Associated Texts ({len(unique_texts)} unique variants, showing up to 3):")
                for i, text_sample in enumerate(unique_texts[:3]):
                    print(f"      - \"{text_sample}\"")
                if len(unique_texts) > 3:
                    print(f"      ... and {len(unique_texts) - 3} more variants.")
            
            print(f"    Found in {len(tag_info['unique_filepaths'])} unique files. Examples of (text, file):")
            for text_ex, file_ex in tag_info['sample_details']:
                 print(f"      - \"{text_ex}\" (from: {file_ex})")

    else:
        print(f"\n--- Frequent Tags Analysis ---")
        print(f"No tags met the frequency threshold of {DUPLICATE_TAG_THRESHOLD} occurrences per mod.")
        
    print(f"-----------------------------------------")
    print(f"Script finished.")