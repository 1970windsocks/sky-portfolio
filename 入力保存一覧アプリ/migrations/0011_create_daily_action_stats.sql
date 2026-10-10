-- 第61課題(データエンジニアリング): audit_logは生ログが増え続ける一方、
-- 「日ごとに何件サインアップがあったか」「ログイン失敗が急増した日はないか」
-- を見るには毎回全件スキャンして集計するしかなかった(list_customers()で
-- 既にやった「集計してから結合する」考え方を、今度は日次トレンド用に適用する)。
-- 日付×action単位で件数を貯めておく小さな集計テーブルを作る。
CREATE TABLE IF NOT EXISTS daily_action_stats (
    stat_date DATE NOT NULL,
    action TEXT NOT NULL,
    count INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (stat_date, action)
);
