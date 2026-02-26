import log from 'electron-log'

log.transports.file.level = 'info'
log.transports.console.level = 'debug'
log.transports.file.maxSize = 10 * 1024 * 1024 // 10 MB

const logger = {
    info: (...args: unknown[]) => log.info(...args),
    warn: (...args: unknown[]) => log.warn(...args),
    error: (...args: unknown[]) => log.error(...args),
    debug: (...args: unknown[]) => log.debug(...args),
}

export default logger
