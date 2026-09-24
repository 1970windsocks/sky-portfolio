# 第52課題(コンテナ・Docker): 「環境ごと持ち運べる箱」を作る。
# 今までRailwayは自動検出(Railpack)でビルドしていたが、
# その中身を自分の手で明示的に定義したのがこのDockerfile。
FROM python:3.12-slim

WORKDIR /app

# 依存関係だけ先にコピーしてインストールすることで、
# コードだけ変更した時の再ビルドを速くする(Dockerのレイヤーキャッシュ)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体をコピー
COPY . .

EXPOSE 8080

# Procfileと同じ起動コマンド。$PORTはRailwayが実行時に注入する。
CMD streamlit run app.py --server.port ${PORT:-8080} --server.address 0.0.0.0
