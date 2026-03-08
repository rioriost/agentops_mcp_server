class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/32/c1/46e4743626732f62d81c6d4360f62a39bf233728783e0e14ce1b67f75301/agentops_mcp_server-0.4.8.tar.gz"
  sha256 "5bd9eb0db1c2164cc78010f280208e247ef06e4c837b92e09a5fb19a8f31b66b"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
