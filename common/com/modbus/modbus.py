from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ExceptionResponse
from typing import Any, Generic, TypeVar, List,Union
import struct


MODBUS_WORD_ORDER = "big"

def swap_bytes(value: int) -> int:
    """Swap the bytes of a 16-bit integer."""
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)

def get_float(data_: list, word_index: int) -> float:
    if data_ and len(data_)>0:
        word1 = data_[word_index]
        word2 = data_[word_index + 1]
        # Combine the two words into a single 32-bit integer
        combined = (word1 << 16) | word2
        # Convert the combined integer to a float
        return float.fromhex(hex(combined))
    return 0.0

def get_double(data_: list, word_index: int) -> float:
    if data_ and len(data_)>0:
        word1 = data_[word_index]
        word2 = data_[word_index + 1]
        word3 = data_[word_index + 2]
        word4 = data_[word_index + 3]
        # Combine the four words into a single 64-bit integer
        combined = (word1 << 48) | (word2 << 32) | (word3 << 16) | word4
        # Convert the combined integer to a double
        return float.fromhex(hex(combined))
    return 0.0

def get_int(data_: list, word_index: int) ->int:
    if data_ and len(data_)>0:
        return data_[word_index]
    return 0

def get_bool(data_: list, word_index: int, bool_index: int) -> bool:
        """Get the boolean value from location in bytearray

        Args:
            bytearray_: buffer data.
            byte_index: byte index to read from.
            bool_index: bit index to read from.

        Returns:
            True if the bit is 1, else 0.

        Examples:
            >>> buffer = bytearray([0b00000001])  # Only one byte length
            >>> get_bool(buffer, 0, 0)  # The bit 0 starts at the right.
                True
        """
        if data_ and len(data_)>0:

            index_value = 1 << bool_index
            word_value = data_[word_index]
            current_value = word_value & index_value
            return current_value == index_value

def set_int(data_: list, word_index: int, value: int):
    """Set integer value on location in bytearray.

    Args:
        bytearray_: buffer to write to.
        byte_index: byte index to write to.
        value: value to write.  
    """
    if data_ and len(data_)>0:
        data_[word_index] = value           


def set_float(data_: list, word_index: int, value: float):
    """Set float value on location in bytearray.

    Args:
        bytearray_: buffer to write to.
        byte_index: byte index to write to.
        value: value to write.  
    """
    if data_ and len(data_)>0:
        # Convert the float to a 32-bit integer representation
        int_value = int.from_bytes(bytearray(struct.pack('f', value)), MODBUS_WORD_ORDER)
        # Split the integer into two 16-bit words
        word1 = (int_value >> 16) & 0xFFFF
        word2 = int_value & 0xFFFF
        # Store the words in the data list
        data_[word_index] = swap_bytes(word1)
        data_[word_index + 1] = swap_bytes(word2)

def set_double(data_: list, word_index: int, value: float):
    """Set double value on location in bytearray.

    Args:
        bytearray_: buffer to write to.
        byte_index: byte index to write to.
        value: value to write.  
    """
    if data_ and len(data_)>0:
        # Convert the double to a 64-bit integer representation
        int_value = int.from_bytes(bytearray(struct.pack('d', value)), MODBUS_WORD_ORDER)
        
        # Split the integer into four 16-bit words
        word1 = (int_value >> 48) & 0xFFFF
        word2 = (int_value >> 32) & 0xFFFF
        word3 = (int_value >> 16) & 0xFFFF
        word4 = int_value & 0xFFFF
        # Store the words in the data list
        data_[word_index]     = swap_bytes(word1)
        data_[word_index + 1] = swap_bytes(word2)
        data_[word_index + 2] = swap_bytes(word3)
        data_[word_index + 3] = swap_bytes(word4)
      



def set_bool(data_: list, word_index: int, bool_index: int, value: bool):
    """Set boolean value on location in bytearray.

    Args:
        bytearray_: buffer to write to.
        word_index: byte index to write to.
        bool_index: bit index to write to.
        value: value to write.

    Examples:
        >>> buffer = bytearray([0b00000000])
        >>> set_bool(buffer, 0, 0, True)
        >>> buffer
            bytearray(b"\\x01")
    """
    if value not in {0, 1, True, False}:
        raise TypeError(f"Value value:{value} is not a boolean expression.")

    current_value = get_bool(data_, word_index, bool_index)
    index_value = 1 << bool_index

    # check if bool already has correct value
    if current_value == value:
        return

    if value:
        # make sure index_v is IN current byte
        data_[word_index] += index_value
    else:
        # make sure index_v is NOT in current byte
        data_[word_index] -= index_value

class ModbusClient:
    def __init__(self):
        self.client = None
        self.connected = False
        
    def connect(self, ip, port=502, timeout=1.0):
        """连接到Modbus TCP服务器"""
        try:
            self.client = ModbusTcpClient(
                host=ip,
                port=port,
                timeout=timeout
            )
            self.connected = self.client.connect()
            return self.connected
        except Exception as e:
            print(f"连接失败: {e}")
            return False
            
    def disconnect(self):
        """断开连接"""
        if self.client:
            self.client.close()
        self.connected = False
        
    def read_coils(self, address, count=1, unit=1):
        """读取线圈状态(0x01功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_coils(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return [bit for bit in response.bits[:count]]
        except ModbusException as e:
            print(f"读取线圈失败: {e}")
            return None
            
    def read_discrete_inputs(self, address, count=1, unit=1):
        """读取离散输入(0x02功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_discrete_inputs(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return [bit for bit in response.bits[:count]]
        except ModbusException as e:
            print(f"读取离散输入失败: {e}")
            return None
            
    def read_holding_registers(self, address, count=1, unit=1):
        """读取保持寄存器(0x03功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_holding_registers(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return response.registers[:count]
        except ModbusException as e:
            print(f"读取保持寄存器失败: {e}")
            return None
            
    def read_input_registers(self, address, count=1, unit=1):
        """读取输入寄存器(0x04功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_input_registers(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return response.registers[:count]
        except ModbusException as e:
            print(f"读取输入寄存器失败: {e}")
            return None
            
    def write_coil(self, address, value, unit=1):
        """写入单个线圈(0x05功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.write_coil(address, value, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入线圈失败: {e}")
            return False
            
    def write_registers(self, address, values: Union[List[int], int], unit=1):
        """写入单个寄存器(0x06功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            if isinstance(values,int):
                response = self.client.write_registers(address, [values], device_id=unit)
            else:
                response = self.client.write_registers(address, values, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入寄存器失败: {e}")
            return False
            
    def write_coils(self, address, values, unit=1):
        """写入多个线圈(0x0F功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.write_coils(address, values, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入多个线圈失败: {e}")
            return False
            
    # def write_registers(self, address, values, unit=1):
    #     """写入多个寄存器(0x10功能码)"""
    #     if not self.connected:
    #         raise RuntimeError("未连接到Modbus设备")
            
    #     try:
    #         response = self.client.write_registers(address, values, device_id=unit)
    #         if isinstance(response, ExceptionResponse):
    #             raise ModbusException(response)
    #         return True
    #     except ModbusException as e:
    #         print(f"写入多个寄存器失败: {e}")
    #         return False
