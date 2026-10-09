-- Cleanup for the dedicated-account tables that were created by an earlier,
-- incorrect migration scope. These tables belong to the OPS-user dedicated
-- account-binding feature, not the SellerSprite crawler shared-account pool.
--
-- This script does not touch the crawler account source, queue account events,
-- account quarantine state, task assignments, or browser profiles.
--
-- Review the database and row counts below first. Change the confirmation value
-- to 1 only when these tables were created by the abandoned migration attempt.

SELECT DATABASE() AS cleanup_database;

SELECT 'seller_sprite_dedicated_accounts' AS table_name, COUNT(*) AS row_count
FROM seller_sprite_dedicated_accounts
UNION ALL
SELECT 'seller_sprite_user_account_bindings', COUNT(*)
FROM seller_sprite_user_account_bindings
UNION ALL
SELECT 'seller_sprite_account_binding_audit', COUNT(*)
FROM seller_sprite_account_binding_audit;

SET @confirm_drop_mistaken_dedicated_account_tables := 0;

DROP PROCEDURE IF EXISTS cleanup_mistaken_seller_sprite_dedicated_account_tables;

DELIMITER $$

CREATE PROCEDURE cleanup_mistaken_seller_sprite_dedicated_account_tables()
BEGIN
    IF @confirm_drop_mistaken_dedicated_account_tables <> 1 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Set @confirm_drop_mistaken_dedicated_account_tables to 1 after reviewing the target database and row counts';
    END IF;

    DROP TABLE IF EXISTS seller_sprite_account_binding_audit;
    DROP TABLE IF EXISTS seller_sprite_user_account_bindings;
    DROP TABLE IF EXISTS seller_sprite_dedicated_accounts;
    DROP TABLE IF EXISTS seller_sprite_account_schema_versions;
END$$

DELIMITER ;

CALL cleanup_mistaken_seller_sprite_dedicated_account_tables();
DROP PROCEDURE cleanup_mistaken_seller_sprite_dedicated_account_tables;
