import { defineComponent } from 'vue'

export const CartView = defineComponent({
  name: 'CartView',
  setup() {
    return () => <div class="cart-view" data-testid="cart-view">购物车</div>
  },
})

export const OrderList = defineComponent({
  name: 'OrderList',
  props: { orders: { type: Array, default: () => [] } },
  setup(props) {
    return () => <ul class="order-list">{props.orders.map((o: unknown) => <li>{JSON.stringify(o)}</li>)}</ul>
  },
})
