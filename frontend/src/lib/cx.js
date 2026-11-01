// Joins class names, skipping falsy ones: cx('a', isOn && 'b', null) -> 'a b'.
export function cx(...classes) {
  return classes.filter(Boolean).join(' ')
}
