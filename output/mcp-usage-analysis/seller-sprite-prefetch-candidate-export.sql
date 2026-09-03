-- SellerSprite 预取候选只读导出，兼容尚未升级缓存指纹列的 Schema v1。
-- MySQL 时间按 UTC 保存；Asia/Shanghai 没有夏令时，使用固定 +8 小时分日。
-- request_params 来自任务 params.json，不导出账号、Session、JWT 或 Cookie。
-- v1 无法确认 shared_pool；导出结果必须结合任务队列或升级后的 cache scope 再审核。

WITH normalized AS (
    SELECT
        source_job_id,
        scenario,
        site,
        COALESCE(
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(request_params, '$.request.period')), 'null'),
            '30d'
        ) AS period,
        COALESCE(
            CAST(JSON_EXTRACT(request_params, '$.request.params') AS CHAR),
            '{}'
        ) AS params_json,
        COALESCE(
            CAST(JSON_UNQUOTE(JSON_EXTRACT(request_params, '$.request.page_size')) AS UNSIGNED),
            100
        ) AS page_size,
        COALESCE(
            NULLIF(JSON_UNQUOTE(JSON_EXTRACT(request_params, '$.request.export_format')), 'null'),
            'json'
        ) AS export_format,
        source_row_count,
        DATE(DATE_ADD(started_at, INTERVAL 8 HOUR)) AS local_date,
        completed_at
    FROM collection_runs
    WHERE data_environment = 'production'
      AND source_system = 'seller_sprite'
      AND collection_status = 'succeeded'
      AND request_params IS NOT NULL
      AND started_at >= UTC_TIMESTAMP(6) - INTERVAL 14 DAY
      AND scenario <> 'listing-analysis'
), candidates AS (
    SELECT
        SHA2(
            CONCAT_WS('|', scenario, site, period, params_json, page_size),
            256
        ) AS candidate_key,
        scenario,
        site,
        period,
        params_json,
        page_size,
        export_format,
        COUNT(DISTINCT local_date) AS active_days,
        COUNT(*) AS successful_runs,
        ROUND(AVG(source_row_count), 1) AS average_rows,
        ROUND(100 * AVG(source_row_count > 0), 1) AS nonzero_rate,
        MAX(completed_at) AS last_completed_at,
        SUBSTRING_INDEX(
            GROUP_CONCAT(source_job_id ORDER BY completed_at DESC SEPARATOR ','),
            ',',
            3
        ) AS sample_source_job_ids
    FROM normalized
    GROUP BY
        candidate_key, scenario, site, period, params_json,
        page_size, export_format
)
SELECT
    candidate_key,
    scenario,
    site,
    period,
    params_json,
    page_size,
    export_format,
    active_days,
    successful_runs,
    average_rows,
    nonzero_rate,
    last_completed_at,
    sample_source_job_ids,
    'requires_shared_pool_verification' AS candidate_status
FROM candidates
WHERE active_days >= 3
  AND successful_runs >= 3
ORDER BY
    active_days DESC,
    successful_runs DESC;
