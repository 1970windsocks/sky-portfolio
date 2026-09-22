-- 第43課題(アルゴリズムと計算量): memos.ownerに索引が無く、
-- db.list_memos()もauth.list_customers()も「全表を1行ずつ端から探す」(Seq Scan)状態だった。
-- 実際に本番でEXPLAINして確認済み(Seq Scan on memos)。
-- 索引を張ることで、探し方が「端から全部」→「索引をたどって一気に絞り込む」に変わる。
CREATE INDEX IF NOT EXISTS idx_memos_owner ON memos (owner);
