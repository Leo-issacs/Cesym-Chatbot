-- cesym_app_role.sql
-- Rol de aplicación least-privilege para que el chatbot escriba cotizaciones en
-- cesym_db. La CONTRASEÑA se define en el servidor (psql) — NUNCA en git.
--
-- Aplicar como superusuario:
--   sudo -u postgres psql -d cesym_db -f cesym_app_role.sql
-- y luego, fuera de git:
--   sudo -u postgres psql -c "ALTER ROLE cesym_app PASSWORD '<definir en server>';"

-- CREATE ROLE cesym_app LOGIN;   -- descomenta si el rol no existe; fija el password aparte
GRANT CONNECT ON DATABASE cesym_db TO cesym_app;
GRANT USAGE ON SCHEMA public TO cesym_app;
GRANT SELECT, INSERT         ON clientes, sucursales TO cesym_app;
GRANT SELECT, INSERT, UPDATE ON cotizaciones         TO cesym_app;
-- IDENTITY no requiere GRANT de secuencia (a diferencia de SERIAL).
