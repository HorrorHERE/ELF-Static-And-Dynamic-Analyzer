#!/bin/bash
DATASET_DIR="./elf_dataset_1000"
mkdir -p "$DATASET_DIR"

find /usr/bin /usr/sbin -type f -executable 2>/dev/null | while read filepath; do
    if file "$filepath" | grep -q "ELF 64-bit"; then
        filename=$(basename "$filepath")
        cp "$filepath" "$DATASET_DIR/$filename" 2>/dev/null
    fi
done


ls -1 "$DATASET_DIR" | shuf | tail -n +1001 | while read f; do
    rm "$DATASET_DIR/$f"
done

echo "Итого файлов: $(ls -1 "$DATASET_DIR" | wc -l)"

echo "filename,has_symbols,is_pie,is_static,size_bytes" > dataset_metadata.csv
for f in "$DATASET_DIR"/*; do
    filename=$(basename "$f")
    has_symbols=$(nm "$f" 2>/dev/null | wc -l)
    is_pie=$(readelf -h "$f" 2>/dev/null | grep -c "DYN")
    is_static=$(readelf -d "$f" 2>/dev/null | grep -c "NEEDED" | awk '{print ($1==0)?1:0}')
    size=$(stat -c%s "$f")
    echo "$filename,$has_symbols,$is_pie,$is_static,$size" >> dataset_metadata.csv
done
