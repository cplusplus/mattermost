const pino = require('pino');

const logger = pino(
    {
        level: process.env.LOG_LEVEL || 'info',
        timestamp: pino.stdTimeFunctions.isoTime,
    },
    process.env.NODE_ENV === 'development' ? pino.transport({ target: 'pino-pretty' }) : undefined
);

module.exports = logger;

if (process.env.CAPTURE_CONSOLE === '1') {
    const clog = logger.child({ subsystem: 'console' });

    const orig = {
        log: console.log.bind(console),
        info: console.info.bind(console),
        warn: console.warn.bind(console),
        error: console.error.bind(console),
    };

    const toStr = (v) => {
        if (typeof v === 'string') return v;
        if (v instanceof Error) return v.stack || v.message;
        try {
            return JSON.stringify(v);
        } catch {
            return String(v);
        }
    };

    const join = (args) => args.map(toStr).join(' ');

    console.log = (...args) => clog.info({ console: true }, join(args));
    console.info = (...args) => clog.info({ console: true }, join(args));
    console.warn = (...args) => clog.warn({ console: true }, join(args));
    console.error = (...args) => clog.error({ console: true }, join(args));

    logger.consoleOriginals = orig;
    clog.info('console.* is captured and forwarded to pino');
}
