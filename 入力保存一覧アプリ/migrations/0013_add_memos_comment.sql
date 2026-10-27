-- 第75課題: メモに「ひとことコメント」を追加できるようにする。
ALTER TABLE memos ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';
