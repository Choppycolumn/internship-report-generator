# 生产（专业）实习报告智能生成与精确套打系统

一个面向固定格式实习报告册的本地工具：用用户实测物理尺寸建立毫米坐标，在扫描模板上标定可打印区域，将中文、照片和图题排到对应位置，并输出预览、正式套打和布局调试三类 PDF。

当前已完成第一至第三阶段：模板与坐标系统、横线文字排版与分页、图片处理与图文混排，以及“每日图片 + 对应文字”的人工审核小程序。完整 8000 字报告自动生成、全文事实审核和最终目录回填仍属于后续阶段，仓库不会把这些能力伪装成已经完成。

<p align="center">
  <img src="docs/images/promo-cover.jpg" width="31%" alt="项目封面">
  <img src="docs/images/promo-workflow.png" width="31%" alt="每日审核流程">
  <img src="docs/images/promo-review.png" width="31%" alt="审核程序界面">
</p>

## 已实现

- 导入 JPG、PNG、TIFF 和 PDF 模板候选，原文件不覆盖。
- 物理宽高为空时禁止毫米标定和正式套打，不猜测 A4。
- 扫描方向、页面边界、透视与旋转校正接口。
- 正文区、禁止区、图片区、字段和横线的毫米坐标配置。
- 逐条真实横线排版、中文标点感知换行、标题绑定和跨页孤行控制。
- 多模板分页、页码区域、越界与固定区域碰撞检查。
- EXIF 方向纠正、清晰度提示、等比例缩放、单图/双图、边框和连续图号。
- 每日照片上传、逐图图题、对应文字和人工确认状态保存。
- 带模板背景预览 PDF、无背景套打 PDF、坐标调试 PDF。
- 打印机偏移、横纵缩放和旋转补偿基础。

## 关键安全边界

- 《使用注意事项》只属于学校要求资料，绝不作为打印模板。
- 新模板的物理宽高默认为空；PDF 介质框和图片 DPI 只作诊断信息。
- 正式套打 PDF 不包含扫描背景、预印页眉、横线、表格或固定文字。
- 推测内容必须先人工确认，不能直接进入正式文件。
- Git 默认忽略学校资料、真实模板、每日照片、学生信息、打印机配置和所有生成文件，避免误传到公开仓库。

## 安装

Windows PowerShell：

```powershell
git clone <repository-url>
cd internship-report-generator
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python cli.py project init
```

启动模板标定界面：

```powershell
.venv\Scripts\streamlit run app.py
```

## 每日图片与文字审核小程序

Windows 下可直接双击：

```text
start_daily_review.cmd
```

也可以从终端启动：

```powershell
.venv\Scripts\python launch_daily_review.py
```

在页面中选择日期并上传多张照片，每张照片下方可填写图题和对应的生成文字，再逐项勾选确认。原图、处理图和审核结果保存在本机 `days/YYYY-MM-DD/`，不会自动上传。

## 模板工作流

导入学校要求资料：

```powershell
.venv\Scripts\python cli.py requirements import <file> --category school_rules
```

导入真正的打印页面扫描件并设置实测尺寸：

```powershell
.venv\Scripts\python cli.py template add <scan_file> --template-id lined_content_page
.venv\Scripts\python cli.py template set-size lined_content_page --width-mm 185 --height-mm 260 --orientation portrait --binding-side left
.venv\Scripts\python cli.py template correct lined_content_page
.venv\Scripts\python cli.py template calibrate lined_content_page
```

人工确认源图四角时，顺序为 TL、TR、BR、BL：

```powershell
.venv\Scripts\python cli.py template correct lined_content_page --corners-px 20,30,2470,25,2460,3480,18,3475
```

只有扫描图边界已经确认就是纸张边界时，才使用 `--use-full-frame`。

横线检测结果默认只是建议；加 `--apply` 才写入配置：

```powershell
.venv\Scripts\python cli.py template detect-lines <template_id>
.venv\Scripts\python cli.py template detect-lines <template_id> --apply
```

## 三类 PDF

- `outputs/previews/`：扫描背景与新增内容，用于目检。
- `outputs/print/`：只含新增内容，用于原报告纸套打。
- `outputs/debug/`：坐标、区域、横线、基线、图片框和打印补偿。

正式打印应选择“实际大小 / 100%”，关闭“适合页面”“缩小过大页面”和自动居中，并先用普通纸试打。

## 合成验收

演示脚本使用明确标记的 `120 × 180 mm` 合成页面，只验证软件行为，不代表任何学校报告纸：

```powershell
.venv\Scripts\python scripts/generate_phase1_example.py
.venv\Scripts\python scripts/generate_phase2_example.py
.venv\Scripts\python scripts/generate_phase3_example.py
.venv\Scripts\python scripts/render_phase3_verification.py
.venv\Scripts\python -m pytest -q
```

当前验收结果：29 项测试通过；三类第三阶段示例 PDF 页数和物理尺寸一致，正式版不含模板背景。

## 当前限制

- 没有用户实测纸张宽高时，不能给出正式精确套打结论。
- 自动横线和表格检测只能作为初始建议，仍需人工校准。
- 每日审核页面目前负责照片与文字对应、保存和确认，不会凭照片虚构事实。
- 完整 8000 字总报告、目录页码回填、全文重复度与事实一致性检查尚未完成。

## License

[MIT](LICENSE)
