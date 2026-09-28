#!/home/Developer/miniconda3/envs/lk-skills/bin/python
# -*- coding: utf-8 -*-
"""
传动轴报价系统 - 生成 PDF+XLSX 报价单
零件：传动轴 φ32x150mm，两端缩径至φ20
材料：6061 铝合金
表面处理：哑光黑色阳极氧化，RA3.2
"""

import sys
# 设置控制台编码为 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json
import os
import math
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass

try:
    import pandas as pd
    print("pandas OK")
except ImportError:
    print("WARNING: pandas not installed")

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.charts.bar import BarChart
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    print("reportlab OK")
except ImportError:
    print("WARNING: reportlab not installed")

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.chart import BarChart, Reference
    print("openpyxl OK")
except ImportError:
    print("WARNING: openpyxl not installed")


@dataclass
class QuoteItem:
    """报价项"""
    quantity: int
    unit_price: float
    total_price: float
    lead_time: int


class TransmissionShaftQuote:
    """传动轴报价计算器"""
    
    def __init__(self):
        # 零件参数
        self.part_name = "传动轴"
        self.part_code = "TS-001"  # 系统标号
        self.material = "6061 铝合金"
        self.density = 2.7  # g/cm³
        self.main_diameter = 32  # mm
        self.main_length = 120  # mm (中间段)
        self.end_diameter = 20  # mm
        self.end_length = 15  # mm (每端)
        self.total_length = 150  # mm
        self.tolerance = "±0.1mm"
        self.surface_treatment = "哑光黑色阳极氧化"
        self.surface_roughness = "RA3.2"
        
        # 成本参数
        self.material_price_per_kg = 25  # 元/kg
        self.machining_rate_per_hour = 80  # 元/小时
        self.surface_treatment_price_per_unit = 30  # 元/件
        
        # 计算体积和重量
        self._calculate_geometry()
    
    def _calculate_geometry(self):
        """计算几何参数"""
        # 中间段体积：π * r² * h
        main_radius = self.main_diameter / 2  # mm
        main_volume = math.pi * (main_radius ** 2) * self.main_length  # mm³
        
        # 两端体积：2 * π * r² * h
        end_radius = self.end_diameter / 2  # mm
        end_volume = 2 * math.pi * (end_radius ** 2) * self.end_length  # mm³
        
        # 总体积
        total_volume_mm3 = main_volume + end_volume
        self.volume_cm3 = total_volume_mm3 / 1000  # cm³
        
        # 重量
        self.weight_g = self.volume_cm3 * self.density
        self.weight_kg = self.weight_g / 1000
        
        # 表面积（用于表面处理）
        main_surface = 2 * math.pi * main_radius * self.main_length  # 侧面积
        end_surface = 2 * 2 * math.pi * end_radius * self.end_length  # 两端侧面积
        end_faces = 2 * math.pi * (main_radius ** 2 - end_radius ** 2)  # 端面环形面积
        self.surface_area_cm2 = (main_surface + end_surface + end_faces) / 100
        
    def calculate_quote(self, quantity: int) -> QuoteItem:
        """计算报价"""
        # 材料成本
        material_cost = self.weight_kg * self.material_price_per_kg
        
        # 加工成本估算（基于体积和复杂度）
        # 简单轴类零件，加工时间约与体积成正比
        machining_time_hours = self.volume_cm3 / 50  # 经验公式
        machining_cost = machining_time_hours * self.machining_rate_per_hour
        
        # 表面处理成本
        surface_cost = self.surface_treatment_price_per_unit
        
        # 总价（单价）
        unit_price = material_cost + machining_cost + surface_cost
        
        # 批量折扣
        if quantity >= 50:
            unit_price *= 0.7  # 7 折
        elif quantity >= 20:
            unit_price *= 0.75  # 75 折
        elif quantity >= 10:
            unit_price *= 0.85  # 85 折
        elif quantity >= 5:
            unit_price *= 0.9  # 9 折
        
        # 总价
        total_price = unit_price * quantity
        
        # 交期估算
        base_days = 3
        if quantity > 50:
            base_days += (quantity - 50) // 10 + 2
        elif quantity > 20:
            base_days += 2
        lead_time = base_days
        
        return QuoteItem(
            quantity=quantity,
            unit_price=round(unit_price, 2),
            total_price=round(total_price, 2),
            lead_time=lead_time
        )
    
    def generate_quotes(self, quantities: List[int]) -> List[QuoteItem]:
        """生成多个数量的报价"""
        return [self.calculate_quote(qty) for qty in quantities]


class QuoteReporter:
    """报价报告生成器"""
    
    def __init__(self, quote_items: List[QuoteItem], part_info: Dict):
        self.items = quote_items
        self.part_info = part_info
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.date_str = datetime.now().strftime("%Y 年%m 月%d 日")
        
    def generate_xlsx(self, filepath: str):
        """生成 Excel 报价单"""
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "报价单"
            
            # 样式
            header_font = Font(bold=True, color="FFFFFF", size=12)
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            title_font = Font(bold=True, size=14)
            align_center = Alignment(horizontal="center", vertical="center")
            border = Border(
                left=Side(style="thin"),
                right=Side(style="thin"),
                top=Side(style="thin"),
                bottom=Side(style="thin")
            )
            
            # 标题
            ws.merge_cells("A1:E1")
            title_cell = ws["A1"]
            title_cell.value = f"{self.part_info['part_name']}报价单"
            title_cell.font = title_font
            title_cell.alignment = align_center
            
            # 零件信息
            ws.merge_cells("A2:E2")
        except Exception as e:
            print(f"ERROR generating XLSX: {e}")
    
    def generate_pdf(self, filepath: str):
        """生成 PDF 报价单"""
        try:
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            elements = []
            styles = getSampleStyleSheet()
            
            # 标题
            title = Paragraph(f"{self.part_info['part_name']}报价单", styles['Title'])
            elements.append(title)
            elements.append(Spacer(1, 20))
            
            # 零件信息表
            info_data = [
                ["零件名称", self.part_info['part_name']],
                ["零件编号", self.part_info['part_code']],
                ["材料", self.part_info['material']],
                ["主要尺寸", f"φ{self.part_info['main_diameter']}x{self.part_info['total_length']}mm"],
                ["公差", self.part_info['tolerance']],
                ["表面处理", self.part_info['surface_treatment']],
                ["表面粗糙度", self.part_info['surface_roughness']],
            ]
            
            info_table = Table(info_data, colWidths=[100, 200])
            info_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'left'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(info_table)
            elements.append(Spacer(1, 20))
            
            # 报价表
            quote_data = [["数量", "单价 (元)", "总价 (元)", "交期 (天)"]]
            for item in self.items:
                quote_data.append([item.quantity, f"{item.unit_price:.2f}", 
                                 f"{item.total_price:.2f}", item.lead_time])
            
            quote_table = Table(quote_data, colWidths=[80, 80, 80, 60])
            quote_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'center'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(quote_table)
            
            doc.build(elements)
            print(f"PDF generated: {filepath}")
        except Exception as e:
            print(f"ERROR generating PDF: {e}")


def main():
    """主函数"""
    # 创建目录结构
    base_dir = r"C:\Users\<user>\Documents\My Workspace (1)\STEP"
    date_str = datetime.now().strftime("%Y%m%d")
    
    # 实例化传动轴报价计算器
    shaft = TransmissionShaftQuote()
    
    # STEP 图纸目录：日期 + 系统标号+AI 生成标识
    step_dir = os.path.join(base_dir, "STEP", f"{date_str}_{shaft.part_code}_AI_GEN")
    os.makedirs(step_dir, exist_ok=True)
    
    # 报价单目录：日期 + 系统标号
    quote_dir = os.path.join(base_dir, "QUOTE", f"{date_str}_{shaft.part_code}")
    os.makedirs(quote_dir, exist_ok=True)
    
    print(f"STEP 目录：{step_dir}")
    print(f"报价目录：{quote_dir}")
    
    # 1. STEP 文件路径（已生成）
    step_file = os.path.join(step_dir, f"TS-001_{datetime.now().strftime('%Y%m%d_%H%M%S')}_AI.step")
    
    print(f"\n📐 STEP 文件将保存至：{step_file}")
    print(f"   (注意：STEP 文件已通过 occ-draw 生成，请复制至上述目录)")
    
    # 2. 计算报价
    shaft = TransmissionShaftQuote()
    quantities = [1, 2, 3, 5, 10, 20, 50]
    quotes = shaft.generate_quotes(quantities)
    
    print(f"\n📊 传动轴几何参数:")
    print(f"  材料：{shaft.material}")
    print(f"  体积：{shaft.volume_cm3:.2f} cm³")
    print(f"  重量：{shaft.weight_g:.2f} g ({shaft.weight_kg:.4f} kg)")
    print(f"  表面积：{shaft.surface_area_cm2:.2f} cm²")
    
    print(f"\n💰 报价结果:")
    for item in quotes:
        print(f"  {item.quantity:2d}件：单价¥{item.unit_price:>8.2f}，总价¥{item.total_price:>10.2f}，交期{item.lead_time}天")
    
    # 3. 生成报价单文件
    part_info = {
        "part_name": shaft.part_name,
        "part_code": shaft.part_code,
        "material": shaft.material,
        "main_diameter": shaft.main_diameter,
        "total_length": shaft.total_length,
        "tolerance": shaft.tolerance,
        "surface_treatment": shaft.surface_treatment,
        "surface_roughness": shaft.surface_roughness,
    }
    
    reporter = QuoteReporter(quotes, part_info)
    
    # 生成 XLSX（简化版）
    xlsx_file = os.path.join(quote_dir, f"报价单_{part_info['part_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "传动轴报价单"
        
        # 标题
        ws['A1'] = f"{part_info['part_name']}报价单"
        ws['A1'].font = Font(bold=True, size=16)
        
        # 零件信息
        ws['A3'] = "零件信息"
        ws['A3'].font = Font(bold=True)
        ws['A4'] = "零件名称:"
        ws['B4'] = part_info['part_name']
        ws['A5'] = "零件编号:"
        ws['B5'] = part_info['part_code']
        ws['A6'] = "材料:"
        ws['B6'] = part_info['material']
        ws['A7'] = "尺寸:"
        ws['B7'] = f"φ{part_info['main_diameter']}x{part_info['total_length']}mm"
        ws['A8'] = "公差:"
        ws['B8'] = part_info['tolerance']
        ws['A9'] = "表面处理:"
        ws['B9'] = part_info['surface_treatment']
        ws['A10'] = "表面粗糙度:"
        ws['B10'] = part_info['surface_roughness']
        
        # 报价表
        ws['A12'] = "报价明细"
        ws['A12'].font = Font(bold=True)
        ws['A14'] = "数量"
        ws['B14'] = "单价 (元)"
        ws['C14'] = "总价 (元)"
        ws['D14'] = "交期 (天)"
        
        for i, item in enumerate(quotes, start=15):
            ws[f'A{i}'] = item.quantity
            ws[f'B{i}'] = f"{item.unit_price:.2f}"
            ws[f'C{i}'] = f"{item.total_price:.2f}"
            ws[f'D{i}'] = item.lead_time
        
        # 样式
        header_cells = [ws['A14'], ws['B14'], ws['C14'], ws['D14']]
        for cell in header_cells:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        
        wb.save(xlsx_file)
        print(f"\n📄 XLSX 报价单已生成：{xlsx_file}")
    except Exception as e:
        print(f"ERROR generating XLSX: {e}")
    
    # 生成 PDF（需要 reportlab）
    pdf_file = os.path.join(quote_dir, f"报价单_{part_info['part_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors  # 添加导入
        
        doc = SimpleDocTemplate(pdf_file, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        # 标题
        title = Paragraph(f"{part_info['part_name']}报价单", styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 20))
        
        # 零件信息表
        info_data = [
            ["零件名称", part_info['part_name']],
            ["零件编号", part_info['part_code']],
            ["材料", part_info['material']],
            ["主要尺寸", f"φ{part_info['main_diameter']}x{part_info['total_length']}mm"],
            ["公差", part_info['tolerance']],
            ["表面处理", part_info['surface_treatment']],
            ["表面粗糙度", part_info['surface_roughness']],
        ]
        
        info_table = Table(info_data, colWidths=[100, 200])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 20))
        
        # 报价表
        quote_data = [["数量", "单价 (元)", "总价 (元)", "交期 (天)"]]
        for item in quotes:
            quote_data.append([item.quantity, f"{item.unit_price:.2f}", 
                             f"{item.total_price:.2f}", item.lead_time])
        
        quote_table = Table(quote_data, colWidths=[80, 80, 80, 60])
        quote_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(quote_table)
        
        doc.build(elements)
        print(f"📄 PDF 报价单已生成：{pdf_file}")
    except Exception as e:
        print(f"ERROR generating PDF: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n✅ 完成！所有文件已保存至:")
    print(f"   STEP 图纸：{step_dir}")
    print(f"   报价单：{quote_dir}")


if __name__ == "__main__":
    main()
