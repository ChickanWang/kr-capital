import { useCallback, useState } from 'react'

/** A size (in px) the user changes by dragging a handle. `fromPointer` turns the pointer position
 * into a size, e.g. distance from the left or bottom edge. Sizes are not remembered: a refresh
 * restores the default layout. */
export function useDragSize({
  initial,
  min,
  max,
  fromPointer,
  cursor,
}: {
  initial: number
  min: number
  max: () => number
  fromPointer: (e: MouseEvent) => number
  cursor: 'col-resize' | 'row-resize'
}): [number, (e: React.MouseEvent) => void] {
  const [size, setSize] = useState(initial)

  const startDrag = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault() // no text selection while dragging
      const onMove = (move: MouseEvent) => setSize(Math.min(max(), Math.max(min, fromPointer(move))))
      const onUp = () => {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        document.body.classList.remove('resizing', cursor)
      }
      document.body.classList.add('resizing', cursor)
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [min, max, fromPointer, cursor],
  )

  return [size, startDrag]
}
