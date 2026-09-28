#!/bin/bash
# 一键生成报价单（所有格式：Excel + Word + HTML + PDF）
# 用法：./generate-all.sh <数据文件.json> <输出文件名>

if [ $# -lt 2 ]; then
    echo "用法：$0 <数据文件.json> <输出文件名>"
    echo "示例：$0 my_quotation.json QT-20260314-001"
    echo ""
    echo "可选参数:"
    echo "  --no-html    跳过 HTML 生成"
    echo "  --html-only  只生成 HTML"
    exit 1
fi

# 解析参数
SKIP_HTML=false
HTML_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-html)
            SKIP_HTML=true
            shift
            ;;
        --html-only)
            HTML_ONLY=true
            shift
            ;;
        *)
            if [ -z "$DATA_FILE" ]; then
                DATA_FILE="$1"
            elif [ -z "$OUTPUT_NAME" ]; then
                OUTPUT_NAME="$1"
            fi
            shift
            ;;
    esac
done

if [ -z "$DATA_FILE" ] || [ -z "$OUTPUT_NAME" ]; then
    echo "❌ 请提供数据文件和输出文件名"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$(dirname "$DATA_FILE")"

# OUTPUT_NAME 只应是无路径的裸文件名；带路径时与 OUTPUT_DIR 拼接会重复目录
# （例如 DATA_FILE=/tmp/t1.json + OUTPUT_NAME=/tmp/T1 → /tmp//tmp/T1.html，写入失败）。
OUTPUT_NAME="$(basename "$OUTPUT_NAME")"
if [ -z "$OUTPUT_NAME" ]; then
    echo "❌ 输出文件名不能为空"
    exit 1
fi

# 检查数据文件
if [ ! -f "$DATA_FILE" ]; then
    echo "❌ 数据文件不存在：$DATA_FILE"
    exit 1
fi

echo "📋 生成报价单..."
echo "数据文件：$DATA_FILE"
echo "输出文件：$OUTPUT_NAME"
echo ""

# 🔴 P0: 运行数据验证（强制）
echo "🔍 运行数据验证..."
VALIDATION_RESULT=$(python3 "$SCRIPT_DIR/quotation_schema.py" 2>&1 <<EOF
{"data_file": "$DATA_FILE"}
EOF
)

# 使用 Python 直接验证数据文件
python3 -c "
import sys
import json
sys.path.insert(0, '$SCRIPT_DIR')
from quotation_schema import validate_quotation_data

with open('$DATA_FILE', 'r', encoding='utf-8') as f:
    data = json.load(f)

valid, errors = validate_quotation_data(data)

if not valid:
    print('❌ 数据验证失败:')
    for err in errors:
        print(f'  - {err}')
    sys.exit(1)
else:
    print('✅ 数据验证通过')
    sys.exit(0)
"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 数据验证失败，报价单生成已终止"
    echo "请检查数据文件，确保使用真实客户信息"
    exit 1
fi

echo ""

# 只生成 HTML 模式
if [ "$HTML_ONLY" = true ]; then
    echo "🌐 生成 HTML..."
    python3 "$SCRIPT_DIR/generate_quotation_html.py" \
      --data "$DATA_FILE" \
      --output "$OUTPUT_DIR/$OUTPUT_NAME.html"
    
    if [ $? -eq 0 ]; then
        echo "✅ HTML: $OUTPUT_NAME.html"
    else
        echo "❌ HTML 生成失败"
        exit 1
    fi
    echo ""
    echo "💡 HTML 已生成，继续导出 PDF..."
fi

# 1-2. Excel / Word（仅完整模式）
# 注：excel-xlsx / word-docx 兄弟技能不在本包内，2026-09-24 起改为
#     缺失即跳过并告警，而非中断整个流水线。
if [ "$HTML_ONLY" = false ]; then
    echo "📗 生成 Excel..."
    if [ -f "$SCRIPT_DIR/../../excel-xlsx/scripts/generate_quotation.py" ]; then
        python3 "$SCRIPT_DIR/../../excel-xlsx/scripts/generate_quotation.py" \
          --data "$DATA_FILE" \
          --output "$OUTPUT_DIR/$OUTPUT_NAME.xlsx" \
          && echo "✅ Excel: $OUTPUT_NAME.xlsx" \
          || echo "⚠️  Excel 生成失败"
    else
        echo "⚠️  excel-xlsx 技能未安装，跳过 Excel"
    fi

    echo "📘 生成 Word..."
    if [ -f "$SCRIPT_DIR/../../word-docx/scripts/generate_quotation_docx.py" ]; then
        python3 "$SCRIPT_DIR/../../word-docx/scripts/generate_quotation_docx.py" \
          --data "$DATA_FILE" \
          --output "$OUTPUT_DIR/$OUTPUT_NAME.docx" \
          && echo "✅ Word: $OUTPUT_NAME.docx" \
          || echo "⚠️  Word 生成失败"
    else
        echo "⚠️  word-docx 技能未安装，跳过 Word"
    fi
fi

# 3. 生成 HTML（html-only 模式上面已生成，避免重复）
if [ "$HTML_ONLY" = false ] && [ "$SKIP_HTML" = false ]; then
    echo "🌐 生成 HTML..."
    python3 "$SCRIPT_DIR/generate_quotation_html.py" \
      --data "$DATA_FILE" \
      --output "$OUTPUT_DIR/$OUTPUT_NAME.html"
    
    if [ $? -eq 0 ]; then
        echo "✅ HTML: $OUTPUT_NAME.html"
    else
        echo "⚠️  HTML 生成失败（继续执行）"
    fi
fi

# 4. 导出 PDF（HTML + Excel）
echo "📄 导出 PDF..."
cd "$OUTPUT_DIR"

# 从 HTML 导出 PDF（使用 Chrome，质量最佳）
HTML_PDF="$OUTPUT_NAME-HTML.pdf"
if [ -f "$OUTPUT_NAME.html" ]; then
    echo "   从 HTML 导出 PDF（高质量）..."
    # macOS Chrome first, then any Linux/Chromium binary on PATH
    CHROME=""
    for c in "$CHROME_OVERRIDE" \
             "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
             "/usr/bin/google-chrome" "/usr/bin/google-chrome-stable" \
             "/usr/bin/chromium" "/usr/bin/chromium-browser" \
             "$(command -v google-chrome 2>/dev/null)" \
             "$(command -v chromium 2>/dev/null)"; do
        [ -x "$c" ] && { CHROME="$c"; break; }
    done
    if [ -x "$CHROME" ]; then
        # A4 大小，优化分页
        "$CHROME" --headless --disable-gpu \
          --print-to-pdf="$HTML_PDF" \
          --print-to-pdf-no-header \
          --print-to-pdf-no-footer \
          --paper-width=8.27 \
          --paper-height=11.69 \
          --margin-top=0.4 \
          --margin-bottom=0.4 \
          --margin-left=0.4 \
          --margin-right=0.4 \
          "file://$(pwd)/$OUTPUT_NAME.html" 2>/dev/null
        
        if [ -f "$HTML_PDF" ]; then
            echo "✅ PDF: $HTML_PDF（Chrome 导出，HTML）"
        fi
    fi

    # Linux/无 Chromium 兜底：soffice 的 Writer/Web 模式转 HTML→PDF
    # （2026-09-24 本机实测：75,638 B 成功，质量次于 Chrome 但可用）
    if [ ! -f "$HTML_PDF" ]; then
        echo "   无 Chromium，改用 LibreOffice 导出 PDF..."
        soffice --headless --convert-to pdf:writer_web_pdf_Export \
          "$OUTPUT_NAME.html" --outdir "$OUTPUT_DIR" >/dev/null 2>&1
        if [ -f "$OUTPUT_DIR/$OUTPUT_NAME.pdf" ]; then
            mv "$OUTPUT_DIR/$OUTPUT_NAME.pdf" "$HTML_PDF"
            echo "✅ PDF: $HTML_PDF（LibreOffice 导出，HTML）"
        else
            echo "⚠️  HTML PDF 导出失败"
        fi
    fi
fi

# 从 Excel 导出 PDF（LibreOffice）
EXCEL_PDF="$OUTPUT_NAME-Excel.pdf"
if [ -f "$OUTPUT_NAME.xlsx" ]; then
    echo "   从 Excel 导出 PDF..."
    soffice --headless --convert-to pdf:calc_pdf_Export "$OUTPUT_NAME.xlsx" --outdir ./ 2>&1
    # LibreOffice 会生成同名的 .pdf 文件
    if [ -f "${OUTPUT_NAME}.pdf" ]; then
        mv "${OUTPUT_NAME}.pdf" "$EXCEL_PDF" 2>/dev/null
        echo "✅ PDF: $EXCEL_PDF（LibreOffice 导出，Excel）"
    else
        echo "⚠️  Excel PDF 导出失败"
    fi
fi

# 5. OKKI 同步（报价单跟进记录）
echo "🔗 同步到 OKKI..."
OKKI_SYNC_SCRIPT="${OKKI_SYNC_SCRIPT:-$SCRIPT_DIR/../../imap-smtp-email/okki-sync.js}"
if [ -f "$OKKI_SYNC_SCRIPT" ]; then
    # 构建 JSON 参数
    SYNC_PARAMS=$(cat <<EOF
{"dataFile":"$DATA_FILE","quotationNo":"$OUTPUT_NAME"}
EOF
)
    
    # 调用 OKKI 同步（失败不阻断流程）
    node "$OKKI_SYNC_SCRIPT" quotation "$SYNC_PARAMS" 2>&1 || true
else
    echo "⚠️  OKKI 同步脚本不存在，跳过同步"
fi

echo ""
echo "🎉 完成！生成文件："
echo "──────────────────────────────────────────"
for f in $OUTPUT_NAME.* $OUTPUT_NAME-*; do
    [ -f "$f" ] && printf "  %-40s %s\n" "$f" "$(du -h "$f" | cut -f1)"
done
echo "──────────────────────────────────────────"
echo "  📁 输出目录: $(pwd)"

echo ""
echo "📄 PDF 导出提示:"
if [ -f "$OUTPUT_DIR/$OUTPUT_NAME.html" ]; then
    echo "   推荐方式：从 HTML 导出 PDF（质量最佳）"
    echo "   1. 在浏览器打开：open $OUTPUT_DIR/$OUTPUT_NAME.html"
    echo "   2. 按 Cmd+P (Mac) 或 Ctrl+P (Windows)"
    echo "   3. 选择 '保存为 PDF'"
    echo "   4. ✅ 勾选 '背景图形'（重要！）"
    echo "   5. 点击保存"
    echo ""
    echo "   或点击右上角的 'Export to PDF' 按钮（如果浏览器支持）"
elif [ -f "$OUTPUT_DIR/$OUTPUT_NAME.pdf" ]; then
    echo "   PDF 已生成：$OUTPUT_DIR/$OUTPUT_NAME.pdf"
fi
