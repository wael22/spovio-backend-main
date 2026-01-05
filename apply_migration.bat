@echo off
REM Script batch pour appliquer la migration tutorial sur app.db
echo ========================================
echo MIGRATION TUTORIAL - app.db
echo ========================================
echo.

python -c "import sqlite3, sys; conn = sqlite3.connect('app.db', timeout=1); c = conn.cursor(); c.execute('ALTER TABLE user ADD COLUMN tutorial_completed BOOLEAN NOT NULL DEFAULT 0'); c.execute('ALTER TABLE user ADD COLUMN tutorial_step INTEGER'); c.execute('UPDATE user SET tutorial_completed = 1'); conn.commit(); print('✅ Migration OK'); conn.close()" 2>nul

if %ERRORLEVEL% == 0 (
    echo.
    echo ✅ SUCCES! La migration a été appliquée.
    echo.
    echo Vous pouvez maintenant redémarrer le serveur:
    echo    python .\app.py
) else (
    echo.
    echo ❌ Échec - La base de données est probablement verrouillée.
    echo.
    echo Assurez-vous d'avoir ARRETE le serveur backend ^(CTRL+C^)
    echo puis relancez ce script.
)

echo.
pause
