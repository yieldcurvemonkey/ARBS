const { Pool } = require('pg');

const indexes = [
  {
    name: 'idx_sdr_event_timestamp',
    sql: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_event_timestamp ON sdr_data("Event timestamp")'
  },
  {
    name: 'idx_sdr_effective_date',
    sql: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_effective_date ON sdr_data("Effective Date")'
  },
  {
    name: 'idx_sdr_maturity_date',
    sql: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_maturity_date ON sdr_data("Maturity date of the underlier")'
  },
  {
    name: 'idx_sdr_notional_currency',
    sql: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_notional_currency ON sdr_data("Notional currency-Leg 1")'
  },
  {
    name: 'idx_sdr_currency_event',
    sql: 'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sdr_currency_event ON sdr_data("Notional currency-Leg 1", "Event timestamp")'
  }
];

async function runIndexes() {
  const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 1
  });

  console.log('🚀 Starting critical index creation...');
  console.log('📊 Creating indexes on 3M+ rows, this will take time...\n');

  for (const index of indexes) {
    console.log(`Creating ${index.name}...`);
    const startTime = Date.now();
    
    try {
      await pool.query(index.sql);
      const duration = ((Date.now() - startTime) / 1000).toFixed(1);
      console.log(`✅ ${index.name} created in ${duration}s\n`);
    } catch (error) {
      if (error.message.includes('already exists')) {
        console.log(`⏭️  ${index.name} already exists\n`);
      } else {
        console.error(`❌ Error creating ${index.name}:`, error.message, '\n');
      }
    }
  }

  console.log('Running ANALYZE to update statistics...');
  await pool.query('ANALYZE sdr_data');
  console.log('✅ ANALYZE complete');

  await pool.end();
  console.log('\n🎉 Index creation complete!');
}

if (!process.env.DATABASE_URL) {
  console.error('DATABASE_URL environment variable required');
  process.exit(1);
}

runIndexes().catch(console.error);