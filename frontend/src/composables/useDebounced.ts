import { ref, watch, type Ref } from "vue";

/** A copy of `source` that catches up only after `delay` ms without a new value. Bind the input to
 * `source` (it stays immediate) and request lists from the returned ref (it waits for typing to pause). */
export function useDebounced<T>(source: Ref<T>, delay = 250): Ref<T> {
  const value = ref(source.value) as Ref<T>;
  let timer: ReturnType<typeof setTimeout> | undefined;
  watch(source, (next) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      value.value = next;
    }, delay);
  });
  return value;
}
