import os
import re

# Путь к папке, в которой нужно производить поиск
DIRECTORY = r"E:\CallRecords\2025\05\03\transcriptions"

# Регулярное выражение для поиска тега:
# [ТИПЗВОНКА:ЦЕЛЕВОЙ], [ТИПЗВОНКА: ЦЕЛЕВОЙ], [ТИП ЗВОНКА:ЦЕЛЕВОЙ], [ТИП ЗВОНКА: ЦЕЛЕВОЙ]
tag_pattern = re.compile(r"\[\s*ТИП\s*ЗВОНКА\s*:\s*ЦЕЛЕВОЙ\s*\]", flags=re.IGNORECASE)

def count_tagged_files(directory):
    total_files = 0
    tagged_files = 0

    # Рекурсивный обход каталога
    for root, dirs, files in os.walk(directory):
        for filename in files:
            total_files += 1
            file_path = os.path.join(root, filename)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if tag_pattern.search(content):
                        tagged_files += 1
            except Exception as e:
                print(f"Не удалось прочитать файл {file_path}: {e}")

    return total_files, tagged_files

if __name__ == "__main__":
    total, tagged = count_tagged_files(DIRECTORY)
    print(f"Всего файлов найдено: {total}")
    print(f"Файлов с тегом [ТИП ЗВОНКА: ЦЕЛЕВОЙ]: {tagged}")
