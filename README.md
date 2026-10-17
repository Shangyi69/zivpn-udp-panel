# ZIVPN Multi-user (zvpn)

ZIVPN UDP server အတွက် user management။ Create / Delete / Renew / Lock / Device limit / Online မြင်ရ။

## Install (VPS, Ubuntu/Debian)

```bash
git clone https://github.com/<you>/zvpn.git
cd zvpn
bash install.sh
```

ထည့်ပြီးရင် `zvpn` ရိုက်ပြီး menu ဖွင့်ပါ။

## Client (ZIVPN app)

- Server: `VPS_IP`
- Port: `5667` (သို့) `6000-19999` ထဲက တစ်ခု
- Password: user ရဲ့ password
- Obfs: app မှာ ထည့်စရာ မလို (server ဘက်က `zivpn`)

## Commands

```
zvpn create <user> <password> <days> <limit>
zvpn delete <user>
zvpn renew <user> <days>
zvpn lock <user> | zvpn unlock <user>
zvpn setlimit <user> <n>
zvpn setpass <user> <password>
zvpn list                 # user, password, expire, limit, online count, status
zvpn online               # online device IP တွေ
zvpn debug                # connect log format စစ်
zvpn sync                 # config ကို user list နဲ့ ပြန် sync
```

## အလုပ်လုပ်ပုံ

- **Auth**: ZIVPN ရဲ့ `auth.config` password list ကို active user တွေ (expire မကျော်၊ lock မဖြစ်) ရဲ့ password နဲ့ ပြည့်ထားတယ်။ ပြောင်းတိုင်း zivpn ကို restart လုပ်တယ်။
- **Expire / Lock**: monitor က ၅ စက္ကန့်တစ်ခါ စစ်ပြီး expire ဖြစ်တဲ့ user ရဲ့ password ကို ဖယ်တယ်။ အလုပ်လုပ်နေတဲ့ session ကိုလည်း DROP လုပ်တယ်။
- **Online**: UDP flow (conntrack) ကို ကြည့်ပြီး သက်ဝင်နေတဲ့ session ကို user နဲ့ ချိတ်တယ်။ User နဲ့ ချိတ်ဖို့ ZIVPN log ထဲက connect line ကို အသုံးပြုတယ် (`zvpn debug` နဲ့ စစ်နိုင်တယ်)။
- **Device limit**: user တစ်ယောက်အတွက် IP အရေအတွက် limit ထက်ကျော်ရင် နောက်ဝင်လာတဲ့ IP ကို iptables DROP နဲ့ ပိတ်တယ်။ အဲဒီ IP flow ပျက်သွားရင် ပြန်ဖွင့်တယ်။

## ZIVPN log format (binary ကို စမ်းပြီး)

```
2026-10-17T02:09:33Z	INFO	server up and running	{"listen": ":5667"}
2026-10-17T02:09:41Z	INFO	client connected	{"addr": "1.2.3.4:5555", "id": "..."}
```

`client connected` line မှာ client address ပါတယ်။ `id` field ထဲမှာ password ပါမှ user နဲ့ ချိတ်နိုင်တယ်။ `zvpn debug` နဲ့ စစ်ပါ။

## ကန့်သတ်ချက်

- Device limit ကို **IP အရေအတွက်** နဲ့ ထိန်းတယ်။ NAT နောက်က device အများကြီးက IP တစ်ခုတည်း ဖြစ်နိုင်တာကြောင့် တိကျမှု မရှိနိုင်ပါ။
- Online/device mapping က ZIVPN log ထဲမှာ connect line နဲ့ password ပါမှ အလုပ်လုပ်တယ်။ `zvpn debug` က မတွေ့ရင် log format ကို ပြောင်းဖို့ လိုနိုင်တယ်။
- Config ပြောင်းတိုင်း zivpn restart ဖြစ်လို့ ချိတ်နေတဲ့ user တွေ ခဏ disconnect ဖြစ်မယ်။
- Traffic (GB) quota ကို ဒီ version မှာ မပါဘူး။

## Uninstall

```bash
bash uninstall.sh              # users ပါ ဖျက်
bash uninstall.sh --keep-users # users ကို ထားခဲ့
```
