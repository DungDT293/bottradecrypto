p = 'exchange/binance_client.py'
text = open(p, 'r', encoding='utf-8').read()
old = '        except (asyncio.TimeoutError, TimeoutError):\n            raise ExchangeAdapterError(f"Hết thời gian chờ phản hồi từ Binance ({self.config.binance.request_timeout_seconds}s Timeout)")'
new = '''        except (asyncio.TimeoutError, TimeoutError):
            if _retry_count < 2:
                print(f"[BINANCE RETRY] Mang Binance bi delay timeout. Dang thu lai lan {_retry_count + 1}...")
                await asyncio.sleep(0.5)
                return await self._request(method, endpoint, params, signed=signed, _retry_count=_retry_count + 1)
            raise ExchangeAdapterError(f"Hết thời gian chờ phản hồi từ Binance ({self.config.binance.request_timeout_seconds}s Timeout)")'''
if old in text:
    open(p, 'w', encoding='utf-8', newline='').write(text.replace(old, new))
    print('Successfully patched timeout retry into binance_client.py!')
else:
    print('Target string not found!')

