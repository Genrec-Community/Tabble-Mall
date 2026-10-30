/**
 * Demo mode: an in-memory stand-in for the API so the frontend can be shown without a backend.
 * Enabled only when DEMO_API=1 (see app/api/v1/[...path]/route.ts). State lives in the server
 * process, so it is shared by every visitor and resets on each cold start.
 */
import type {
  CartLineOut,
  CategoryOut,
  CustomerOrderOut,
  CustomerStoreOrderOut,
  MallOut,
  OrgOut,
  PrinterOut,
  ProductOut,
  SettingsOut,
  StaffOut,
  StoreOrderOut,
  StoreOrderStatus,
  StoreOut,
} from "@/lib/api";

const now = () => new Date().toISOString();
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
let seq = 1;
const uuid = () => {
  const n = (seq++).toString(16).padStart(12, "0");
  return `0190d000-0000-7000-8000-${n}`;
};

const PERMISSIONS = [
  "audit.read", "org.billing.manage", "org.mall.manage", "org.settings.update", "org.staff.manage",
  "org.store.manage", "platform.kyc.approve", "platform.org.manage", "store.kyc.submit",
  "store.order.cancel", "store.order.print", "store.order.read", "store.order.update",
  "store.order.verify_pickup", "store.printer.manage", "store.product.read", "store.product.write",
  "store.profile.update", "store.report.read", "store.staff.manage", "store.stock.update",
  "store.theme.update",
];
const STORE_PERMISSIONS = PERMISSIONS.filter((p) => p.startsWith("store."));

const org: OrgOut = {
  id: uuid(), name: "Demo Malls Pvt Ltd", slug: "demo-malls", status: "active",
  commission_bps: 500, accept_timeout_s: 300, created_at: ago(60 * 24 * 30),
};
const mall: MallOut = {
  id: uuid(), organization_id: org.id, name: "Demo Mall", slug: "demo-mall", status: "active",
  address: "MG Road", city: "Bengaluru",
};

interface DemoProduct { name: string; diet: "veg" | "nonveg" | "egg"; price: number; description: string; sizes?: [string, number][] }
interface DemoStore { name: string; slug: string; description: string; food_types: string[]; menu: Record<string, DemoProduct[]> }

const STORE_SEED: DemoStore[] = [
  {
    name: "Spice Route", slug: "spice-route", description: "North Indian curries and tandoor",
    food_types: ["north_indian", "meals"],
    menu: {
      Starters: [
        { name: "Paneer Tikka", diet: "veg", price: 24000, description: "Char-grilled cottage cheese" },
        { name: "Chicken 65", diet: "nonveg", price: 26000, description: "Spicy fried chicken" },
      ],
      Mains: [
        { name: "Butter Chicken", diet: "nonveg", price: 32000, description: "Creamy tomato gravy" },
        { name: "Dal Makhani", diet: "veg", price: 22000, description: "Slow-cooked black lentils" },
        { name: "Veg Biryani", diet: "veg", price: 25000, description: "Basmati rice, vegetables, raita", sizes: [["Half", 18000], ["Full", 25000]] },
      ],
      Breads: [{ name: "Garlic Naan", diet: "veg", price: 6000, description: "Tandoor-baked" }],
    },
  },
  {
    name: "Dosa Corner", slug: "dosa-corner", description: "South Indian breakfast all day",
    food_types: ["south_indian", "snacks"],
    menu: {
      Dosas: [
        { name: "Masala Dosa", diet: "veg", price: 12000, description: "Potato masala, chutney, sambar" },
        { name: "Ghee Roast", diet: "veg", price: 14000, description: "Crisp and buttery" },
        { name: "Egg Dosa", diet: "egg", price: 13000, description: "Topped with egg" },
      ],
      Tiffin: [
        { name: "Idli Vada", diet: "veg", price: 9000, description: "2 idli, 1 vada" },
        { name: "Filter Coffee", diet: "veg", price: 5000, description: "Strong and frothy" },
      ],
    },
  },
  {
    name: "Wok Express", slug: "wok-express", description: "Indo-Chinese noodles and rice",
    food_types: ["chinese", "fast_food"],
    menu: {
      Noodles: [
        { name: "Hakka Noodles", diet: "veg", price: 18000, description: "Tossed with vegetables" },
        { name: "Chicken Schezwan Noodles", diet: "nonveg", price: 22000, description: "Fiery Schezwan sauce" },
      ],
      Rice: [{ name: "Egg Fried Rice", diet: "egg", price: 19000, description: "Wok-tossed rice" }],
      Starters: [{ name: "Gobi Manchurian", diet: "veg", price: 17000, description: "Crispy cauliflower" }],
    },
  },
  {
    name: "Sip & Scoop", slug: "sip-and-scoop", description: "Shakes, juices and ice cream",
    food_types: ["beverages", "desserts"],
    menu: {
      Shakes: [
        { name: "Cold Coffee", diet: "veg", price: 15000, description: "With a scoop of vanilla", sizes: [["Regular", 15000], ["Large", 19000]] },
        { name: "Oreo Shake", diet: "veg", price: 17000, description: "Cookies and cream" },
      ],
      Desserts: [
        { name: "Brownie Sundae", diet: "egg", price: 16000, description: "Warm brownie, ice cream" },
        { name: "Fresh Lime Soda", diet: "veg", price: 8000, description: "Sweet or salted" },
      ],
    },
  },
];

const stores: StoreOut[] = [];
const settings = new Map<string, SettingsOut>();
const categories = new Map<string, CategoryOut[]>();
const products = new Map<string, ProductOut[]>();
const storeMeta = new Map<string, DemoStore>();

for (const seed of STORE_SEED) {
  const store: StoreOut = {
    id: uuid(), mall_id: mall.id, organization_id: org.id, name: seed.name, slug: seed.slug,
    description: seed.description, status: "active", commission_bps: null,
  };
  stores.push(store);
  storeMeta.set(store.id, seed);
  settings.set(store.id, {
    store_id: store.id, accepting_orders: true, auto_print: true, banner_key: null, banner_url: null,
    bill_when: "accepted", kot_when: "accepted", food_types: seed.food_types, fssai: null, gstin: null,
    hours: [{ days: [0, 1, 2, 3, 4, 5, 6], open: "10:00", close: "22:00" }], is_open: true,
    is_paused: false, logo_key: null, logo_url: null, theme: { primary: "#111827", accent: "#f59e0b", font: "system", template: 1 },
    timezone: "Asia/Kolkata",
  });
  const cats: CategoryOut[] = [];
  const prods: ProductOut[] = [];
  Object.entries(seed.menu).forEach(([catName, items], ci) => {
    const cat = { id: uuid(), name: catName, position: ci };
    cats.push(cat);
    items.forEach((p, pi) => {
      prods.push({
        id: uuid(), store_id: store.id, category_id: cat.id, name: p.name, description: p.description,
        diet: p.diet, allergens: null, image_key: null, image_url: null, is_available: true,
        position: pi, prep_minutes: 12, stock_mode: "manual", tax_bps: 500, windows: [],
        option_groups: [],
        variants: (p.sizes ?? [["Regular", p.price]]).map(([name, price]) => ({
          id: uuid(), name, price_paise: price, stock_count: null,
        })),
      });
    });
  });
  categories.set(store.id, cats);
  products.set(store.id, prods);
}

const roleName: Record<string, string> = {
  platform_admin: "Platform Admin", org_owner: "Org Owner", org_manager: "Org Manager",
  store_owner: "Store Owner", store_staff: "Store Staff",
};
const ROLES = [
  { key: "platform_admin", scope_type: "platform", permissions: PERMISSIONS, grantable_by: ["platform_admin"] },
  { key: "org_owner", scope_type: "organization", permissions: PERMISSIONS.filter((p) => !p.startsWith("platform.")), grantable_by: ["platform_admin", "org_owner"] },
  { key: "org_manager", scope_type: "organization", permissions: PERMISSIONS.filter((p) => !p.startsWith("platform.") && !["store.kyc.submit", "org.settings.update", "org.billing.manage", "audit.read"].includes(p)), grantable_by: ["platform_admin", "org_owner"] },
  { key: "store_owner", scope_type: "store", permissions: STORE_PERMISSIONS, grantable_by: ["platform_admin", "org_owner", "store_owner"] },
  { key: "store_staff", scope_type: "store", permissions: ["store.order.read", "store.order.update", "store.order.verify_pickup", "store.order.print", "store.product.read", "store.stock.update"], grantable_by: ["platform_admin", "org_owner", "org_manager", "store_owner"] },
].map((r) => ({ ...r, name: roleName[r.key] }));

const demoStaffId = uuid();
const firstStore = stores[0];
const assignment = (role_key: string, scope: { organization_id?: string; mall_id?: string; store_id?: string }) => ({
  id: uuid(), role_key, role_name: roleName[role_key],
  scope_type: (scope.store_id ? "store" : scope.mall_id ? "mall" : scope.organization_id ? "organization" : "platform") as "store" | "mall" | "organization" | "platform",
  organization_id: scope.organization_id ?? null, mall_id: scope.mall_id ?? null, store_id: scope.store_id ?? null,
});

const staff: StaffOut[] = [
  {
    id: demoStaffId, username: "demo", display_name: "Demo Admin", email: "demo@example.com", status: "active",
    must_change_password: false, totp_enabled: true, last_login_at: now(),
    grants: [
      assignment("platform_admin", {}),
      assignment("org_owner", { organization_id: org.id }),
      assignment("store_owner", { organization_id: org.id, mall_id: mall.id, store_id: firstStore.id }),
    ],
  },
  {
    id: uuid(), username: "priya.manager", display_name: "Priya (Manager)", email: null, status: "active",
    must_change_password: false, totp_enabled: false, last_login_at: ago(90),
    grants: [assignment("org_manager", { organization_id: org.id })],
  },
  ...stores.map((s, i) => ({
    id: uuid(), username: `${s.slug}.counter`, display_name: `${s.name} Counter`, email: null,
    status: "active" as const, must_change_password: false, totp_enabled: false, last_login_at: ago(10 + i * 7),
    grants: [assignment("store_staff", { organization_id: org.id, mall_id: mall.id, store_id: s.id })],
  })),
];

function staffMe() {
  const me = staff[0];
  return {
    id: me.id, username: me.username, display_name: me.display_name, must_change_password: false,
    totp_enabled: true,
    grants: me.grants.map((g) => ({
      role_key: g.role_key, scope_type: g.scope_type, organization_id: g.organization_id,
      mall_id: g.mall_id, store_id: g.store_id,
      permissions: ROLES.find((r) => r.key === g.role_key)?.permissions ?? [],
    })),
  };
}

const customer = { id: uuid(), name: "Demo Customer", email: null, has_phone: true, phone_masked: "+91 ••••• ••210" };

// ---- orders -------------------------------------------------------------------------------

interface DemoOrder { customer: CustomerOrderOut; storeOrders: { storeId: string; order: StoreOrderOut }[] }
const orders: DemoOrder[] = [];
let orderNo = 101;

function linesFrom(cartLines: CartLineOut[]) {
  return cartLines.map((l) => ({
    name: l.product_name, variant_name: l.variant_name, diet: l.diet, quantity: l.quantity,
    unit_price_paise: l.unit_price_paise, line_total_paise: l.line_total_paise, note: l.note, options: [],
  }));
}

function placeOrder(byStore: { storeId: string; lines: CartLineOut[] }[], status: StoreOrderStatus, minutesAgo: number) {
  const created = ago(minutesAgo);
  const customerOrderId = uuid();
  const storeOrders: DemoOrder["storeOrders"] = [];
  const customerStores: CustomerStoreOrderOut[] = [];
  for (const { storeId, lines } of byStore) {
    const store = stores.find((s) => s.id === storeId)!;
    const total = lines.reduce((sum, l) => sum + l.line_total_paise, 0);
    const steps = [{ status: "paid" as StoreOrderStatus, at: created }];
    const flow: StoreOrderStatus[] = ["accepted", "preparing", "ready", "picked_up"];
    for (const s of flow.slice(0, Math.max(0, flow.indexOf(status) + 1))) steps.push({ status: s, at: created });
    const order: StoreOrderOut = {
      id: uuid(), store_id: storeId, order_no: orderNo++, status, created_at: created,
      accept_by: status === "paid" ? new Date(Date.parse(created) + 5 * 60_000).toISOString() : null,
      accepted_at: status === "paid" ? null : created, ready_at: null, picked_up_at: null,
      customer_name: customer.name, customer_phone: "+91•••••43210", note: null, reason: null,
      prep_minutes: 15, tax_paise: Math.round(total * 0.05), total_paise: total, lines: linesFrom(lines), steps,
    };
    storeOrders.push({ storeId, order });
    customerStores.push({
      id: order.id, store_name: store.name, store_slug: store.slug, order_no: order.order_no,
      status, created_at: created, accept_by: order.accept_by, lines: order.lines, note: null,
      pickup_code: String(1000 + Math.floor(Math.random() * 9000)), prep_minutes: 15, reason: null,
      steps, tax_paise: order.tax_paise, total_paise: total,
    });
  }
  const customerOrder: CustomerOrderOut = {
    id: customerOrderId, created_at: created, mall_slug: mall.slug, status: "paid", stores: customerStores,
    total_paise: customerStores.reduce((s, o) => s + o.total_paise, 0),
  };
  orders.unshift({ customer: customerOrder, storeOrders });
  return customerOrder;
}

function cartLine(storeIndex: number, productIndex: number, quantity: number): CartLineOut {
  const p = products.get(stores[storeIndex].id)![productIndex];
  const v = p.variants[0];
  return {
    id: uuid(), product_id: p.id, product_name: p.name, variant_name: v.name, diet: p.diet, quantity,
    unit_price_paise: v.price_paise, line_total_paise: v.price_paise * quantity, note: null, options: [], problem: null,
  };
}

placeOrder([{ storeId: stores[0].id, lines: [cartLine(0, 2, 1), cartLine(0, 5, 2)] }, { storeId: stores[3].id, lines: [cartLine(3, 0, 2)] }], "paid", 2);
placeOrder([{ storeId: stores[0].id, lines: [cartLine(0, 0, 1)] }], "preparing", 9);
placeOrder([{ storeId: stores[0].id, lines: [cartLine(0, 3, 1), cartLine(0, 5, 1)] }, { storeId: stores[1].id, lines: [cartLine(1, 0, 2)] }], "ready", 18);
placeOrder([{ storeId: stores[2].id, lines: [cartLine(2, 0, 1)] }], "picked_up", 60 * 26);

const ACTIVE: StoreOrderStatus[] = ["paid", "accepted", "preparing", "ready"];

function syncCustomer(storeOrder: StoreOrderOut) {
  for (const o of orders) {
    const c = o.customer.stores.find((s) => s.id === storeOrder.id);
    if (c) { c.status = storeOrder.status; c.steps = storeOrder.steps; c.reason = storeOrder.reason; }
  }
}

function transition(storeId: string, orderId: string, status: StoreOrderStatus, reason: string | null = null) {
  const so = orders.flatMap((o) => o.storeOrders).find((s) => s.storeId === storeId && s.order.id === orderId);
  if (!so) return null;
  const at = now();
  so.order.status = status;
  so.order.steps = [...so.order.steps, { status, at }];
  if (status === "accepted") so.order.accepted_at = at;
  if (status === "ready") so.order.ready_at = at;
  if (status === "picked_up") so.order.picked_up_at = at;
  if (reason) so.order.reason = reason;
  syncCustomer(so.order);
  return so.order;
}

// ---- cart ---------------------------------------------------------------------------------

let cart: { storeId: string; line: CartLineOut }[] = [];

function cartOut() {
  const byStore = stores
    .map((s) => ({ store: s, lines: cart.filter((c) => c.storeId === s.id).map((c) => c.line) }))
    .filter((g) => g.lines.length > 0)
    .map(({ store, lines }) => ({
      store_name: store.name, store_slug: store.slug, accepting_orders: true, prep_minutes: 15, lines,
      subtotal_paise: lines.reduce((s, l) => s + l.line_total_paise, 0),
    }));
  return {
    mall_slug: mall.slug, stores: byStore, can_checkout: byStore.length > 0,
    total_paise: byStore.reduce((s, g) => s + g.subtotal_paise, 0),
  };
}

// ---- public views -------------------------------------------------------------------------

function publicProduct(p: ProductOut) {
  return {
    id: p.id, name: p.name, description: p.description, diet: p.diet, allergens: p.allergens,
    image_url: p.image_url ?? null, prep_minutes: p.prep_minutes, available: p.is_available,
    unavailable_reason: p.is_available ? null : ("sold_out" as const),
    variants: p.variants.map((v) => ({ id: v.id, name: v.name, price_paise: v.price_paise, available: true })),
    option_groups: [],
  };
}

function storeCard(s: StoreOut) {
  const st = settings.get(s.id)!;
  return {
    name: s.name, slug: s.slug, description: s.description, logo_url: null,
    food_types: st.food_types, accepting_orders: st.is_open && !st.is_paused,
  };
}

const activeStores = () => stores.filter((s) => s.status === "active");

// ---- router -------------------------------------------------------------------------------

type Body = Record<string, unknown>;
type Handler = (p: Record<string, string>, body: Body, query: URLSearchParams) => unknown;
const routes: [string, RegExp, string[], Handler][] = [];
function on(method: string, pattern: string, handler: Handler) {
  const keys: string[] = [];
  const re = new RegExp(`^${pattern.replace(/\{(\w+)\}/g, (_, k: string) => { keys.push(k); return "([^/]+)"; })}$`);
  routes.push([method, re, keys, handler]);
}

export class DemoError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
const notFound = () => { throw new DemoError(404, "Not found"); };
const NO_CONTENT = Symbol("no-content");

const token = () => ({ access_token: `demo.${Date.now()}`, token_type: "bearer", expires_in: 900 });
const storeOf = (id: string) => stores.find((s) => s.id === id) ?? notFound();
const storeBySlug = (slug: string) => activeStores().find((s) => s.slug === slug) ?? notFound();
const storeOrderOf = (storeId: string, id: string) =>
  orders.flatMap((o) => o.storeOrders).find((s) => s.storeId === storeId && s.order.id === id)?.order ?? notFound();
const page = <T,>(items: T[]) => ({ items, next_cursor: null });
const storeOrdersWhere = (pred: (storeId: string) => boolean, view: string | null) =>
  orders.flatMap((o) => o.storeOrders).filter((s) => pred(s.storeId))
    .map((s) => s.order)
    .filter((o) => (view === "active" ? ACTIVE.includes(o.status) : view === "history" ? !ACTIVE.includes(o.status) : true));
const staffWhere = (pred: (g: StaffOut["grants"][number]) => boolean) => staff.filter((s) => s.grants.some(pred));

// auth
for (const kind of ["staff", "customer"]) {
  on("POST", `/auth/${kind}/refresh`, token);
  on("POST", `/auth/${kind}/logout`, () => NO_CONTENT);
}
on("POST", "/auth/staff/login", token);
on("POST", "/auth/staff/logout-all", () => NO_CONTENT);
on("POST", "/auth/staff/password", () => NO_CONTENT);
on("GET", "/auth/staff/me", staffMe);
on("GET", "/auth/staff/sessions", () => [
  { id: uuid(), created_at: ago(30), last_seen_at: now(), current: true, ip: "203.0.113.7", user_agent: "This browser" },
]);
on("POST", "/auth/staff/totp/setup", () => ({ secret: "DEMODEMODEMODEMO", otpauth_uri: "otpauth://totp/MallT:demo?secret=DEMODEMODEMODEMO" }));
on("POST", "/auth/staff/totp/confirm", () => NO_CONTENT);
on("POST", "/auth/customer/otp/request", () => ({ expires_in: 300 }));
on("POST", "/auth/customer/otp/verify", token);
on("POST", "/auth/customer/phone/verify", token);
on("POST", "/auth/customer/google", token);
on("GET", "/auth/customer/me", () => customer);
on("PATCH", "/auth/customer/me", (_, b) => Object.assign(customer, b));
on("GET", "/health", () => ({ status: "ok" }));
on("GET", "/ready", () => ({ status: "ok" }));
on("GET", "/roles", () => ROLES);

// public
on("GET", "/public/malls/{slug}", ({ slug }) =>
  slug !== mall.slug ? notFound() : {
    name: mall.name, slug: mall.slug, city: mall.city,
    stores: activeStores().map((s) => ({ name: s.name, slug: s.slug, description: s.description })),
  });
on("GET", "/public/malls/{mall}/stores", ({ mall: slug }) => (slug !== mall.slug ? notFound() : activeStores().map(storeCard)));
on("GET", "/public/malls/{mall}/items", ({ mall: slug }, _, q) => {
  if (slug !== mall.slug) notFound();
  const text = q.get("q")?.toLowerCase();
  const diet = q.get("diet");
  const foodType = q.get("food_type");
  const storeSlug = q.get("store");
  const items = activeStores()
    .filter((s) => !storeSlug || s.slug === storeSlug)
    .filter((s) => !foodType || settings.get(s.id)!.food_types.includes(foodType))
    .flatMap((s) => products.get(s.id)!.map((p) => ({ s, p })))
    .filter(({ p }) => (!text || p.name.toLowerCase().includes(text)) && (!diet || p.diet === diet))
    .map(({ s, p }) => ({ store_name: s.name, store_slug: s.slug, accepting_orders: true, product: publicProduct(p) }));
  return page(items);
});
on("GET", "/public/malls/{mall}/stores/{store}/menu", ({ mall: slug, store: storeSlug }) => {
  if (slug !== mall.slug) notFound();
  const s = storeBySlug(storeSlug);
  const st = settings.get(s.id)!;
  return {
    store: { ...storeCard(s), banner_url: null, hours: st.hours, theme: st.theme },
    categories: categories.get(s.id)!.map((c) => ({
      id: c.id, name: c.name,
      products: products.get(s.id)!.filter((p) => p.category_id === c.id).map(publicProduct),
    })),
  };
});

// cart & customer orders
on("GET", "/malls/{slug}/cart", cartOut);
on("DELETE", "/malls/{slug}/cart", () => { cart = []; return NO_CONTENT; });
on("POST", "/malls/{slug}/cart/lines", (_, b) => {
  const variantId = String(b.variant_id ?? "");
  for (const s of stores) {
    for (const p of products.get(s.id)!) {
      const v = p.variants.find((x) => x.id === variantId) ?? (p.id === b.product_id ? p.variants[0] : undefined);
      if (!v) continue;
      const quantity = Number(b.quantity ?? 1);
      const existing = cart.find((c) => c.line.product_id === p.id && c.line.variant_name === v.name);
      if (existing) {
        existing.line.quantity += quantity;
        existing.line.line_total_paise = existing.line.quantity * existing.line.unit_price_paise;
      } else {
        cart.push({ storeId: s.id, line: {
          id: uuid(), product_id: p.id, product_name: p.name, variant_name: v.name, diet: p.diet, quantity,
          unit_price_paise: v.price_paise, line_total_paise: v.price_paise * quantity,
          note: typeof b.note === "string" ? b.note : null, options: [], problem: null,
        } });
      }
      return cartOut();
    }
  }
  return notFound();
});
on("PATCH", "/malls/{slug}/cart/lines/{line}", ({ line }, b) => {
  const c = cart.find((x) => x.line.id === line) ?? notFound();
  const quantity = Number(b.quantity ?? c.line.quantity);
  if (quantity <= 0) cart = cart.filter((x) => x !== c);
  else { c.line.quantity = quantity; c.line.line_total_paise = quantity * c.line.unit_price_paise; }
  return cartOut();
});
on("POST", "/malls/{slug}/checkout", () => {
  if (cart.length === 0) throw new DemoError(409, "Your cart is empty");
  const byStore = [...new Set(cart.map((c) => c.storeId))].map((storeId) => ({
    storeId, lines: cart.filter((c) => c.storeId === storeId).map((c) => c.line),
  }));
  cart = [];
  return placeOrder(byStore, "paid", 0);
});
on("GET", "/orders", () => page(orders.map((o) => o.customer)));
on("GET", "/orders/{id}", ({ id }) => orders.find((o) => o.customer.id === id)?.customer ?? notFound());
on("POST", "/orders/stores/{id}/cancel", ({ id }) => {
  const o = orders.find((x) => x.storeOrders.some((s) => s.order.id === id)) ?? notFound();
  const so = o.storeOrders.find((s) => s.order.id === id)!;
  transition(so.storeId, id, "cancelled", "Cancelled by customer");
  return o.customer;
});

// platform & org
on("GET", "/orgs", () => page([org]));
on("POST", "/orgs", (_, b) => ({ org: { ...org, id: uuid(), name: String(b.name ?? "New org"), slug: String(b.slug ?? "new-org") }, owner_username: String(b.owner_username ?? "owner"), temp_password: "Demo-Temp-1234" }));
on("GET", "/orgs/{id}", ({ id }) => (id === org.id ? org : notFound()));
on("PATCH", "/orgs/{id}", (_, b) => Object.assign(org, b));
on("POST", "/orgs/{id}/activate", () => Object.assign(org, { status: "active" }));
on("POST", "/orgs/{id}/suspend", () => Object.assign(org, { status: "suspended" }));
const audit = () => page([
  { id: uuid(), action: "store.settings.update", actor_type: "staff", actor_id: demoStaffId, actor_username: "demo", target_type: "store", target_id: firstStore.id, organization_id: org.id, before: { is_paused: true }, after: { is_paused: false }, created_at: ago(15) },
  { id: uuid(), action: "staff.create", actor_type: "staff", actor_id: demoStaffId, actor_username: "demo", target_type: "staff", target_id: staff[1].id, organization_id: org.id, before: null, after: { username: "priya.manager" }, created_at: ago(60 * 5) },
  { id: uuid(), action: "mall.create", actor_type: "staff", actor_id: demoStaffId, actor_username: "demo", target_type: "mall", target_id: mall.id, organization_id: org.id, before: null, after: { name: mall.name }, created_at: ago(60 * 24 * 7) },
]);
on("GET", "/orgs/{id}/audit", audit);
on("GET", "/admin/audit", audit);
on("GET", "/orgs/{id}/malls", () => [mall]);
on("POST", "/orgs/{id}/malls", (_, b) => ({ ...mall, id: uuid(), name: String(b.name ?? "New mall"), slug: String(b.slug ?? "new-mall") }));
on("GET", "/orgs/{id}/orders", (_, __, q) => page(storeOrdersWhere(() => true, q.get("view"))));
on("GET", "/orgs/{id}/staff", ({ id }) => staffWhere((g) => g.organization_id === id));
on("GET", "/malls/{id}", ({ id }) => (id === mall.id ? mall : notFound()));
on("PATCH", "/malls/{id}", (_, b) => Object.assign(mall, b));
on("POST", "/malls/{id}/activate", () => Object.assign(mall, { status: "active" }));
on("POST", "/malls/{id}/suspend", () => Object.assign(mall, { status: "suspended" }));
on("GET", "/malls/{id}/orders", (_, __, q) => page(storeOrdersWhere(() => true, q.get("view"))));
on("GET", "/malls/{id}/staff", ({ id }) => staffWhere((g) => g.mall_id === id));
on("GET", "/malls/{id}/stores", () => stores);
on("POST", "/malls/{id}/stores", (_, b) => {
  const s: StoreOut = { id: uuid(), mall_id: mall.id, organization_id: org.id, name: String(b.name ?? "New store"), slug: String(b.slug ?? `store-${stores.length + 1}`), description: (b.description as string) ?? null, status: "active", commission_bps: null };
  stores.push(s);
  settings.set(s.id, { ...settings.get(firstStore.id)!, store_id: s.id, food_types: [] });
  categories.set(s.id, []);
  products.set(s.id, []);
  return s;
});

// staff
function createStaff(scope: { organization_id?: string; mall_id?: string; store_id?: string }, b: Body) {
  const s: StaffOut = {
    id: uuid(), username: String(b.username ?? "new.staff"), display_name: String(b.display_name ?? b.username ?? "New staff"),
    email: (b.email as string) ?? null, status: "active", must_change_password: true, totp_enabled: false, last_login_at: null,
    grants: [assignment(String(b.role_key ?? "store_staff"), scope)],
  };
  staff.push(s);
  return { staff: s, temp_password: "Demo-Temp-1234" };
}
on("POST", "/orgs/{id}/staff", ({ id }, b) => createStaff({ organization_id: id }, b));
on("POST", "/malls/{id}/staff", ({ id }, b) => createStaff({ organization_id: org.id, mall_id: id }, b));
on("POST", "/stores/{id}/staff", ({ id }, b) => createStaff({ organization_id: org.id, mall_id: mall.id, store_id: id }, b));
const staffOf = (id: string) => staff.find((s) => s.id === id) ?? notFound();
on("POST", "/staff/{id}/activate", ({ id }) => Object.assign(staffOf(id), { status: "active" }));
on("POST", "/staff/{id}/suspend", ({ id }) => Object.assign(staffOf(id), { status: "suspended" }));
on("POST", "/staff/{id}/reset-password", () => ({ temp_password: "Demo-Temp-5678" }));
on("POST", "/staff/{id}/roles", ({ id }, b) => {
  const s = staffOf(id);
  const scopeId = (b.scope_id as string) ?? undefined;
  const type = String(b.scope_type);
  const a = assignment(String(b.role_key), type === "store" ? { organization_id: org.id, mall_id: mall.id, store_id: scopeId } : type === "mall" ? { organization_id: org.id, mall_id: scopeId } : type === "organization" ? { organization_id: scopeId } : {});
  s.grants.push(a);
  return a;
});
on("DELETE", "/staff/{id}/roles/{assignment}", ({ id, assignment: a }) => {
  const s = staffOf(id);
  s.grants = s.grants.filter((g) => g.id !== a);
  return NO_CONTENT;
});

// stores
on("GET", "/stores/{id}", ({ id }) => storeOf(id));
on("PATCH", "/stores/{id}", ({ id }, b) => Object.assign(storeOf(id), b));
on("POST", "/stores/{id}/activate", ({ id }) => Object.assign(storeOf(id), { status: "active" }));
on("POST", "/stores/{id}/suspend", ({ id }) => Object.assign(storeOf(id), { status: "suspended" }));
on("GET", "/stores/{id}/staff", ({ id }) => staffWhere((g) => g.store_id === id));
on("GET", "/stores/{id}/settings", ({ id }) => settings.get(id) ?? notFound());
on("PATCH", "/stores/{id}/settings", ({ id }, b) => Object.assign(settings.get(id) ?? notFound(), b));
on("GET", "/stores/{id}/categories", ({ id }) => categories.get(id) ?? notFound());
on("POST", "/stores/{id}/categories", ({ id }, b) => {
  const list = categories.get(id) ?? notFound();
  const c = { id: uuid(), name: String(b.name ?? "New category"), position: list.length };
  list.push(c);
  return c;
});
on("PATCH", "/stores/{id}/categories/{cat}", ({ id, cat }, b) => Object.assign((categories.get(id) ?? []).find((c) => c.id === cat) ?? notFound(), b));
on("DELETE", "/stores/{id}/categories/{cat}", ({ id, cat }) => {
  categories.set(id, (categories.get(id) ?? []).filter((c) => c.id !== cat));
  return NO_CONTENT;
});
const productOf = (storeId: string, id: string) => (products.get(storeId) ?? []).find((p) => p.id === id) ?? notFound();
function productFrom(storeId: string, b: Body, base?: ProductOut): ProductOut {
  const variants = Array.isArray(b.variants)
    ? (b.variants as Body[]).map((v) => ({ id: uuid(), name: String(v.name ?? "Regular"), price_paise: Number(v.price_paise ?? 0), stock_count: (v.stock_count as number) ?? null }))
    : base?.variants ?? [];
  return {
    ...(base ?? {
      id: uuid(), store_id: storeId, image_key: null, image_url: null, is_available: true, position: (products.get(storeId) ?? []).length,
      option_groups: [], windows: [],
    }),
    name: String(b.name ?? base?.name ?? "New product"), description: (b.description as string) ?? base?.description ?? null,
    category_id: (b.category_id as string) ?? base?.category_id ?? null, diet: (b.diet as ProductOut["diet"]) ?? base?.diet ?? "veg",
    allergens: (b.allergens as string) ?? base?.allergens ?? null, prep_minutes: Number(b.prep_minutes ?? base?.prep_minutes ?? 10),
    stock_mode: (b.stock_mode as ProductOut["stock_mode"]) ?? base?.stock_mode ?? "manual", tax_bps: Number(b.tax_bps ?? base?.tax_bps ?? 500),
    variants,
  };
}
on("GET", "/stores/{id}/products", ({ id }) => products.get(id) ?? notFound());
on("POST", "/stores/{id}/products", ({ id }, b) => {
  const p = productFrom(id, b);
  (products.get(id) ?? notFound()).push(p);
  return p;
});
on("GET", "/stores/{id}/products/{pid}", ({ id, pid }) => productOf(id, pid));
on("PUT", "/stores/{id}/products/{pid}", ({ id, pid }, b) => {
  const list = products.get(id) ?? notFound();
  const i = list.findIndex((p) => p.id === pid);
  if (i < 0) notFound();
  list[i] = productFrom(id, b, list[i]);
  return list[i];
});
on("DELETE", "/stores/{id}/products/{pid}", ({ id, pid }) => {
  products.set(id, (products.get(id) ?? []).filter((p) => p.id !== pid));
  return NO_CONTENT;
});
on("PATCH", "/stores/{id}/products/{pid}/availability", ({ id, pid }, b) => {
  const p = productOf(id, pid);
  if (typeof b.is_available === "boolean") p.is_available = b.is_available;
  return p;
});
on("POST", "/stores/{id}/images/presign", () => { throw new DemoError(503, "Image uploads are turned off in the demo"); });

// store orders
on("GET", "/stores/{id}/orders", ({ id }, _, q) => page(storeOrdersWhere((s) => s === id, q.get("view"))));
on("GET", "/stores/{id}/orders/{oid}", ({ id, oid }) => storeOrderOf(id, oid));
const step = (status: StoreOrderStatus): Handler => ({ id, oid }, b) => {
  storeOrderOf(id, oid);
  return transition(id, oid, status, typeof b.reason === "string" ? b.reason : null);
};
on("POST", "/stores/{id}/orders/{oid}/accept", step("accepted"));
on("POST", "/stores/{id}/orders/{oid}/preparing", step("preparing"));
on("POST", "/stores/{id}/orders/{oid}/ready", step("ready"));
on("POST", "/stores/{id}/orders/{oid}/pickup", step("picked_up"));
on("POST", "/stores/{id}/orders/{oid}/reject", step("rejected"));
on("POST", "/stores/{id}/orders/{oid}/cancel", step("cancelled"));
on("POST", "/stores/{id}/orders/{oid}/print", () => ({ queued: 2 }));

// printing
const printers = new Map<string, PrinterOut[]>();
const printersOf = (storeId: string) => {
  if (!printers.has(storeId)) {
    printers.set(storeId, [
      { id: uuid(), name: "Kitchen printer", role: "kitchen", connection: "lan", target: "192.168.1.50:9100", paper_width: 80, is_active: true, last_printed_at: ago(9), layout: {} },
      { id: uuid(), name: "Counter printer", role: "counter", connection: "usb", target: "EPSON TM-T82", paper_width: 80, is_active: true, last_printed_at: ago(9), layout: {} },
    ]);
  }
  return printers.get(storeId)!;
};
const agentFor = (storeId: string) => ({ id: storeId, name: "Counter PC", token_prefix: "pa_demo", version: "1.0.0", is_active: true, online: true, last_seen_at: now(), created_at: ago(60 * 24 * 3) });
on("GET", "/stores/{id}/print-agents", ({ id }) => [agentFor(id)]);
on("POST", "/stores/{id}/print-agents", ({ id }) => ({ agent: agentFor(id), token: "pa_demo_token_not_real" }));
on("POST", "/stores/{id}/print-agents/{aid}/revoke", ({ id }) => ({ ...agentFor(id), is_active: false, online: false }));
on("POST", "/stores/{id}/print-agents/{aid}/rotate", ({ id }) => ({ agent: agentFor(id), token: "pa_demo_token_not_real" }));
on("POST", "/stores/{id}/print-agents/{aid}/scan", () => ({ requested: true }));
on("GET", "/stores/{id}/detected-printers", ({ id }) => [
  { agent_id: id, agent_name: "Counter PC", key: "usb:epson", name: "EPSON TM-T82", connection: "usb", target: "EPSON TM-T82", driver: "ESC/POS", is_default: true, likely_thermal: true },
]);
on("GET", "/stores/{id}/printers", ({ id }) => printersOf(id));
on("POST", "/stores/{id}/printers", ({ id }, b) => {
  const p: PrinterOut = { id: uuid(), name: String(b.name ?? "Printer"), role: (b.role as PrinterOut["role"]) ?? "kitchen", connection: (b.connection as PrinterOut["connection"]) ?? "lan", target: String(b.target ?? ""), paper_width: Number(b.paper_width ?? 80), is_active: true, last_printed_at: null, layout: (b.layout as PrinterOut["layout"]) ?? {} };
  printersOf(id).push(p);
  return p;
});
on("PATCH", "/stores/{id}/printers/{pid}", ({ id, pid }, b) => Object.assign(printersOf(id).find((p) => p.id === pid) ?? notFound(), b));
const job = (printerId: string, kind: "ticket" | "bill" | "test", minutesAgo: number) => ({ id: uuid(), printer_id: printerId, kind, status: "printed" as const, attempts: 1, last_error: null, store_order_id: null, created_at: ago(minutesAgo), acked_at: ago(minutesAgo) });
on("POST", "/stores/{id}/printers/{pid}/test", ({ pid }) => ({ ...job(pid, "test", 0), status: "queued", acked_at: null }));
on("GET", "/stores/{id}/print-jobs", ({ id }) => { const [k, c] = printersOf(id); return [job(k.id, "ticket", 9), job(c.id, "bill", 9), job(k.id, "ticket", 18)]; });
const design = { header_name: null as string | null, header_address: "MG Road, Bengaluru", header_phone: "080 1234 5678", header_extra: null, footer_text: "Thank you! Visit again.", has_logo: false, options: {} };
on("GET", "/stores/{id}/print-design", ({ id }) => ({ ...design, header_name: design.header_name ?? storeOf(id).name }));
on("PUT", "/stores/{id}/print-design", (_, b) => Object.assign(design, b));
on("PUT", "/stores/{id}/print-design/logo", () => design);
on("DELETE", "/stores/{id}/print-design/logo", () => design);

/** Handle one /api/v1 request. Returns [status, body]; body undefined means no content. */
export function handleDemo(method: string, path: string, body: Body, query: URLSearchParams): [number, unknown] {
  for (const [m, re, keys, handler] of routes) {
    if (m !== method) continue;
    const match = re.exec(path);
    if (!match) continue;
    const params = Object.fromEntries(keys.map((k, i) => [k, decodeURIComponent(match[i + 1])]));
    const result = handler(params, body, query);
    if (result === NO_CONTENT) return [204, undefined];
    return [method === "POST" && /\/(staff|stores|malls|orgs|categories|products|printers|print-agents|cart\/lines|roles)$/.test(path) ? 201 : 200, result];
  }
  return [404, { title: "Not found", status: 404, detail: "Not available in the demo" }];
}
