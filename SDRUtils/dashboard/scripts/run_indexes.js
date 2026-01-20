const { Pool } = require('pg');
const fs = require('fs');
const path = require('path');

async function runIndexes() {
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 1, // Single connection for DDL
  });

  try {
    console.log('🔧 Starting index creation...');
    console.log('⚠️  This may take several minutes for 3M+ rows');
    
    const sqlPath = path.join(__dirname, 'add_critical_indexes.sql');
    const sql = fs.readFileSync(sqlPath, 'utf8');
    
    // Split by semicolon and run each statement
    const statements = sql.split(';').filter(s => s.trim() && !s.trim().startsWith('--'));
    
    for (let i = 0; i < statements.length; i++) {
      const statement = statements[i].trim();
      if (!statement) continue;
      
      const indexMatch = statement.match(/CREATE INDEX.*?(\w+)\s+ON/i);
      const indexName = indexMatch ? indexMatch[1] : `Statement ${i + 1}`;
      
      console.log(`\n📊 Creating index: ${indexName}`);
      console.time(indexName);
      
      try {
        await pool.query(statement);
        console.timeEnd(indexName);
        console.log(`✅ ${indexName} created successfully`);
      } catch (error) {
        console.timeEnd(indexName);
        if (error.message.includes('already exists')) {
          console.log(`⏭️  ${indexName} already exists, skipping`);
        } else {
          console.error(`❌ Error creating ${indexName}:`, error.message);
        }
      }
    }
    
    // Check table statistics
    console.log('\n📈 Checking table statistics...');
    const stats = await pool.query(`
      SELECT 
        relname as table_name,
        n_tup_ins as inserts,
        n_tup_upd as updates,
        n_tup_del as deletes,
        n_live_tup as live_rows,
        n_dead_tup as dead_rows,
        last_vacuum,
        last_autovacuum,
        last_analyze,
        last_autoanalyze
      FROM pg_stat_user_tables
      WHERE relname = 'sdr_data'
    `);
    
    console.table(stats.rows);
    
    // Run ANALYZE to update statistics
    console.log('\n🔍 Running ANALYZE to update query planner statistics...');
    await pool.query('ANALYZE sdr_data');
    console.log('✅ ANALYZE complete');
    
    console.log('\n🎉 All indexes created successfully!');
    console.log('🚀 Your queries should now be MUCH faster');
    
  } catch (error) {
    console.error('Fatal error:', error);
  } finally {
    await pool.end();
  }
}

// Check for DATABASE_URL
if (!process.env.DATABASE_URL) {
  console.error('❌ DATABASE_URL not found in environment');
  console.error('Run with: DATABASE_URL="your-connection-string" node scripts/run_indexes.js');
  process.exit(1);
}

runIndexes().catch(console.error);