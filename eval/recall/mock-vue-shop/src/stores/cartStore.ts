import { defineStore } from 'pinia'

export const useCartStore = defineStore('cart', {
  state: () => ({ items: [] as Array<{ id: number; qty: number }> }),
  actions: {
    addItem(id: number, qty: number) {
      this.items.push({ id, qty })
    },
    clear() {
      this.items = []
    },
  },
})

export async function fetchOrders(page = 1) {
  const res = await fetch(`/api/orders?page=${page}`)
  return res.json()
}

export function formatPrice(cents: number): string {
  return (cents / 100).toFixed(2)
}
