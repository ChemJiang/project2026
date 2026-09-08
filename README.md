# Robotic Arm Digital Manufacturing Portfolio

A bilingual Streamlit portfolio that connects four project stages through a left sidebar:

1. **SolidWorks Modeling** — assembly render, motion demonstration and downloadable SLDASM/SLDPRT source package.
2. **AnyLogic Simulation** — six-operation process model, resource assumptions, scenario comparison and simulation evidence.
3. **MES System** — SQLite-backed work orders, production execution, quality/defect handling and traceability.
4. **Six Sigma Analysis** — validated `quality_data_v5_final` capability, stability, MSA, root-cause and control-plan results.

## Run

```bash
pip install -r requirements.txt
python database/init_db.py
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. Use the left sidebar for the four project sections and the upper-right language selector for English or Chinese.

## Deploy with GitHub and Streamlit Community Cloud

1. Create a public GitHub repository and upload the **contents of this folder** to the repository root.
2. Confirm that `app.py`, `requirements.txt`, `.streamlit/config.toml`, `data/`, `database/`, `services/` and `assets/` are visible in the repository.
3. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/) with GitHub.
4. Select **Create app**, choose the repository and `main` branch, and set the main file path to `streamlit_app.py`.
5. In **Advanced settings**, select Python 3.12, then deploy.

The hosted SQLite database is suitable for a portfolio demonstration. Changes made by visitors can be shared during one running instance and may reset when the cloud app restarts.

## 中文说明

本项目通过左侧栏串联 **SolidWorks 建模、AnyLogic 仿真、MES 系统、六西格玛分析** 四个阶段。运行上面的命令后，在浏览器打开 `http://localhost:8501`；右上角可切换中英文。
