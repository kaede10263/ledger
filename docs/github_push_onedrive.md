# GitHub Push Notes for OneDrive Workspace

專案位置：

```powershell
C:\Users\chunw\OneDrive\github\golden_UI
```

GitHub repository：

```text
https://github.com/kaede10263/ledger
```

## 第一次設定

```powershell
cd C:\Users\chunw\OneDrive\github\golden_UI
conda activate golden
git init
git branch -M main
git remote add origin https://github.com/kaede10263/ledger.git
git add .
git commit -m "Initial portfolio dashboard"
git push -u origin main
```

## 日常更新

```powershell
cd C:\Users\chunw\OneDrive\github\golden_UI
conda activate golden
git status
git add .
git commit -m "Update portfolio dashboard"
git push
```

## 注意

- 不需要移到 temporary 資料夾；直接在 OneDrive 專案資料夾操作即可。
- `.gitignore` 會排除 `portfolio.db`、`*.db`、`build/`、`dist/`、`__pycache__/`。
- 若 OneDrive 正在同步，先等同步完成再 push，避免檔案被鎖或 git 狀態一直變動。
