import type { ComponentListItem } from '../api'

export type BuildMap = Record<string, ComponentListItem | null>

export function specVal(item: ComponentListItem | null | undefined, labels: string[]): string {
  if (!item?.specs) return ''
  for (const k of labels) {
    for (const [ak, av] of Object.entries(item.specs)) {
      const a = ak.toLowerCase()
      const b = k.toLowerCase()
      if (a === b || a.includes(b) || b.includes(a)) return String(av || '')
    }
  }
  return ''
}

export function normalizeSocket(raw: string): string {
  let s = (raw || '').toLowerCase()
  s = s.replace(/socket|сокет/gi, '')
  s = s.replace(/\s+/g, '')
  const m =
    s.match(/am\d+/i) ||
    s.match(/lga\d+/i) ||
    s.match(/strx\d+/i) ||
    s.match(/trx\d+/i) ||
    s.match(/fm\d+/i)
  if (m) return m[0].toLowerCase()
  return s.trim()
}

export function extractDdr(raw: string): string {
  if (!raw) return ''
  const m = String(raw).match(/ddr\s*([45])/i)
  return m ? `ddr${m[1]}` : ''
}

export function itemSocket(item: ComponentListItem | null | undefined): string {
  if (!item) return ''
  return specVal(item, ['Сокет', 'Socket'])
}

export function itemMemType(item: ComponentListItem | null | undefined): string {
  if (!item) return ''
  return specVal(item, ['Тип памяти', 'Memory Type', 'DDR'])
}

/** DDR из спеки + названия + модели */
export function itemDdr(item: ComponentListItem | null | undefined): string {
  if (!item) return ''
  const fromSpec = extractDdr(itemMemType(item))
  if (fromSpec) return fromSpec
  const blob = [item.name, item.model, item.description, JSON.stringify(item.specs || {})]
    .filter(Boolean)
    .join(' ')
  return extractDdr(blob)
}

/**
 * Поколение памяти по сокету.
 * AM5 → DDR5; AM4 → DDR4. Для Intel сокет сам по себе
 * не определяет тип памяти: LGA1700 и некоторые LGA1151 платы бывают DDR4/DDR5.
 */
export function platformDdrFromSocket(socketRaw: string): string {
  const s = normalizeSocket(socketRaw)
  if (!s) return ''
  if (s.includes('am5') || s.includes('str5') || s.includes('sp5')) return 'ddr5'
  if (s.includes('am4')) return 'ddr4'
  // Intel memory generation is board-specific on several sockets; do not guess.
  if (/lga\s*1200/.test(s)) return 'ddr4'
  return ''
}

export function requiredDdrForBuild(build: BuildMap): string {
  const mb = build.motherboard
  const ram = build.ram
  const cpu = build.cpu

  if (mb) {
    const fromMb = itemDdr(mb)
    if (fromMb) return fromMb
    const fromSock = platformDdrFromSocket(itemSocket(mb))
    if (fromSock) return fromSock
  }
  if (cpu) {
    const fromSock = platformDdrFromSocket(itemSocket(cpu))
    if (fromSock) return fromSock
  }
  if (ram) {
    const fromRam = itemDdr(ram)
    if (fromRam) return fromRam
  }
  return ''
}

export function socketsMatch(a: string, b: string): boolean {
  if (!a?.trim() || !b?.trim()) return true
  const na = normalizeSocket(a)
  const nb = normalizeSocket(b)
  if (!na || !nb) return true
  return na === nb || na.includes(nb) || nb.includes(na)
}

/**
 * AM5-плата → ОЗУ только DDR5 (DDR4 скрыты).
 * AM4-плата → ОЗУ только DDR4.
 * Выбрана DDR4 ОЗУ → платы AM5 скрыты.
 */
export function isCompatibleWithBuild(
  slotKey: string,
  item: ComponentListItem,
  build: BuildMap,
): boolean {
  const cpu = build.cpu
  const mb = build.motherboard
  const ram = build.ram
  const requiredDdr = requiredDdrForBuild(build)

  if (slotKey === 'cpu') {
    if (mb) {
      const a = itemSocket(item)
      const b = itemSocket(mb)
      if (a && b && !socketsMatch(a, b)) return false
    }
    return true
  }

  if (slotKey === 'motherboard') {
    if (cpu) {
      const a = itemSocket(item)
      const b = itemSocket(cpu)
      if (a && b && !socketsMatch(a, b)) return false
    }
    if (ram) {
      const ramDdr = itemDdr(ram)
      if (ramDdr) {
        const mbDdr = itemDdr(item) || platformDdrFromSocket(itemSocket(item))
        if (mbDdr && mbDdr !== ramDdr) return false
        if (ramDdr === 'ddr4') {
          const sock = normalizeSocket(itemSocket(item))
          if (sock.includes('am5')) return false
        }
        if (ramDdr === 'ddr5') {
          const sock = normalizeSocket(itemSocket(item))
          if (sock.includes('am4') && !sock.includes('am5')) return false
        }
      }
    }
    return true
  }

  if (slotKey === 'ram') {
    const itemD = itemDdr(item)
    if (requiredDdr) {
      if (itemD && itemD !== requiredDdr) return false
      if (!itemD) {
        const nameD = extractDdr(item.name || '')
        if (nameD && nameD !== requiredDdr) return false
      }
      if (requiredDdr === 'ddr5') {
        const blob = `${item.name} ${item.model || ''} ${itemMemType(item)}`.toLowerCase()
        if (/ddr\s*4/.test(blob) && !/ddr\s*5/.test(blob)) return false
      }
      if (requiredDdr === 'ddr4') {
        const blob = `${item.name} ${item.model || ''} ${itemMemType(item)}`.toLowerCase()
        if (/ddr\s*5/.test(blob) && !/ddr\s*4/.test(blob)) return false
      }
    }
    if (mb) {
      const a = itemD
      const b = itemDdr(mb) || platformDdrFromSocket(itemSocket(mb))
      if (a && b && a !== b) return false
    }
    return true
  }

  if (slotKey === 'cooler') {
    const coolSock = itemSocket(item)
    if (coolSock) {
      if (cpu) {
        const b = itemSocket(cpu)
        if (b && !socketsMatch(coolSock, b)) return false
      }
      if (mb) {
        const b = itemSocket(mb)
        if (b && !socketsMatch(coolSock, b)) return false
      }
    }
    return true
  }

  return true
}

export function checkCompat(build: BuildMap): string[] {
  const warns: string[] = []
  const cpu = build.cpu
  const mb = build.motherboard
  const ram = build.ram

  if (cpu && mb) {
    const sockCpu = itemSocket(cpu)
    const sockMb = itemSocket(mb)
    if (sockCpu && sockMb && !socketsMatch(sockCpu, sockMb)) {
      warns.push(`Сокет: процессор «${sockCpu}» и плата «${sockMb}» несовместимы`)
    }
  }
  if (mb && ram) {
    const typeMb = itemDdr(mb) || platformDdrFromSocket(itemSocket(mb)) || itemMemType(mb)
    const typeRam = itemDdr(ram) || itemMemType(ram)
    const da = extractDdr(typeMb) || (typeMb || '').toLowerCase()
    const db = extractDdr(typeRam) || (typeRam || '').toLowerCase()
    if (da && db && da !== db) {
      warns.push(`Несовместимо: плата/платформа «${typeMb}», ОЗУ «${typeRam}»`)
    }
  }
  if (mb) {
    const sock = normalizeSocket(itemSocket(mb))
    if (sock.includes('am5')) {
      const ramDdr = ram ? itemDdr(ram) : ''
      if (ramDdr === 'ddr4') {
        warns.push('Сокет AM5 работает только с DDR5 — DDR4 установить нельзя')
      }
    }
    if (sock.includes('am4') && !sock.includes('am5')) {
      const ramDdr = ram ? itemDdr(ram) : ''
      if (ramDdr === 'ddr5') {
        warns.push('Сокет AM4 работает только с DDR4 — DDR5 установить нельзя')
      }
    }
  }
  return warns
}

export function ddrLockMessage(
  build: BuildMap,
  activeSlot: string | null,
): string | null {
  const req = requiredDdrForBuild(build)
  if (!req) return null
  const sock =
    (build.motherboard && itemSocket(build.motherboard)) ||
    (build.cpu && itemSocket(build.cpu)) ||
    ''
  const sockN = normalizeSocket(sock)
  if (activeSlot === 'ram') {
    if (req === 'ddr5') {
      return sockN.includes('am5')
        ? 'Плата/сокет AM5 — показаны только модули DDR5. DDR4 выбрать нельзя.'
        : 'По выбранной плате доступна только память DDR5.'
    }
    if (req === 'ddr4') {
      return sockN.includes('am4')
        ? 'Плата/сокет AM4 — показаны только модули DDR4. DDR5 выбрать нельзя.'
        : 'По выбранной плате доступна только память DDR4.'
    }
  }
  if (activeSlot === 'motherboard' && build.ram) {
    const rd = itemDdr(build.ram)
    if (rd === 'ddr4') return 'Выбрана ОЗУ DDR4 — платы AM5 (только DDR5) скрыты.'
    if (rd === 'ddr5') return 'Выбрана ОЗУ DDR5 — платы только под DDR4 (например AM4) скрыты.'
  }
  return null
}
