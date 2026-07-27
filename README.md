# AEDT Model Path Re-mapper

用於掃描 Ansys Electronics Desktop（AEDT）專案中的模型檔案路徑，找出失效連結，並依檔名自動搜尋與重新指定檔案位置。

## 主要功能

- 掃描 `.aedt` 專案中的 Touchstone、IBIS、SPICE、AMI、CSV 等模型路徑。
- 顯示檔案存在狀態與引用次數。
- 依指定資料夾遞迴搜尋遺失檔案。
- 套用變更前自動建立時間戳備份。

## 使用環境

- Ansys Electronics Desktop（AEDT）
- 建議使用與專案相容的 AEDT 版本

## 使用方式

1. 開啟 AEDT。
2. 選擇 `Automation > Run Script...`。
3. 開啟 `AEDT_Model_Path_Remapper.py`。
4. 依介面選擇 `.aedt` 專案與模型搜尋資料夾。

## 注意事項

請先備份原始專案。Repository 中的 AEDT 專案僅作為展示用途，未包含客戶專案資料。

如需企業流程整合、批次處理或客製化功能，請來信洽詢。

此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供
